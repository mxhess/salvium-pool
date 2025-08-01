#!/usr/bin/env python3
"""
Salvium Pool Data API Server - Aggregated Stats
Collects stats from multiple pool nodes and aggregates them
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import redis
import json
import time
from datetime import datetime, timedelta
import logging
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Configuration
REDIS_HOST = 'core.supportsal.com'
REDIS_PORT = 6379
REDIS_DB = 0
API_PORT = 5000

# Pool nodes configuration
POOL_NODES = [
    'http://core.supportsal.com:4243',    # Upstream - has shares/blocks/balances
    'http://node1.supportsal.com:4243',   # Downstream - has live miner data
    # Add new nodes here as you scale:
    # 'http://node2.supportsal.com:4243',
    # 'http://node3.supportsal.com:4243',
]

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend

# Initialize Redis connection
try:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
    r.ping()
    print(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
except Exception as e:
    print(f"Failed to connect to Redis: {e}")
    exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache for aggregated stats
stats_cache = {"data": None, "timestamp": 0}
stats_lock = threading.Lock()

def fetch_node_stats(node_url, address=None, timeout=3):
    """Fetch stats from a single pool node"""
    try:
        headers = {}
        if address:
            headers['Cookie'] = f'wa={address}'
        
        response = requests.get(f'{node_url}/stats', headers=headers, timeout=timeout)
        if response.status_code == 200:
            data = response.json()
            data['node_url'] = node_url
            return data
        else:
            logger.warning(f"Node {node_url} returned status {response.status_code}")
            return None
    except Exception as e:
        logger.warning(f"Failed to fetch from {node_url}: {e}")
        return None

def fetch_node_workers(node_url, address, timeout=3):
    """Fetch workers from a single pool node"""
    try:
        headers = {'Cookie': f'wa={address}'}
        response = requests.get(f'{node_url}/workers', headers=headers, timeout=timeout)
        if response.status_code == 200:
            workers = response.json()
            # Add node info to each worker
            for worker in workers:
                if isinstance(worker, dict):
                    worker['node'] = node_url
            return workers
        else:
            return []
    except Exception as e:
        logger.warning(f"Failed to fetch workers from {node_url}: {e}")
        return []

def aggregate_pool_stats(node_stats_list, address=None):
    """Aggregate stats from multiple nodes"""
    if not node_stats_list:
        return None
    
    # Use the first node's network stats (should be same across all nodes)
    base_stats = node_stats_list[0]
    
    aggregated = {
        # Network stats (same across all nodes)
        "network_hashrate": base_stats.get("network_hashrate", 0),
        "network_difficulty": base_stats.get("network_difficulty", 0),
        "network_height": base_stats.get("network_height", 0),
        "last_template_fetched": max(node.get("last_template_fetched", 0) for node in node_stats_list),
        
        # Pool settings (use first node's settings)
        "payment_threshold": base_stats.get("payment_threshold", 0.1),
        "pool_fee": base_stats.get("pool_fee", 0.007),
        "pool_port": base_stats.get("pool_port", 4242),
        "pool_ssl_port": base_stats.get("pool_ssl_port", 4343),
        "allow_self_select": base_stats.get("allow_self_select", 1),
        
        # Aggregated pool stats
        "pool_hashrate": sum(node.get("pool_hashrate", 0) for node in node_stats_list),
        "round_hashes": sum(node.get("round_hashes", 0) for node in node_stats_list),
        "connected_miners": sum(node.get("connected_miners", 0) for node in node_stats_list),
        "pool_blocks_found": sum(node.get("pool_blocks_found", 0) for node in node_stats_list),
        "last_block_found": max(node.get("last_block_found", 0) for node in node_stats_list),
        
        # Miner-specific stats (if address provided)
        "miner_hashrate": sum(node.get("miner_hashrate", 0) for node in node_stats_list),
        "miner_balance": sum(node.get("miner_balance", 0) for node in node_stats_list),
        "worker_count": sum(node.get("worker_count", 0) for node in node_stats_list),
        
        # Additional info
        "timestamp": int(time.time()),
        "active_nodes": len([n for n in node_stats_list if n.get("pool_hashrate", 0) > 0]),
        "total_nodes": len(node_stats_list),
        "nodes_info": [{"url": n.get("node_url", "unknown"), 
                       "hashrate": n.get("pool_hashrate", 0),
                       "miners": n.get("connected_miners", 0)} for n in node_stats_list]
    }
    
    # Calculate miner hashrate stats (aggregate the arrays)
    miner_hr_stats = [0, 0, 0, 0, 0, 0]
    for node in node_stats_list:
        node_hr_stats = node.get("miner_hashrate_stats", [0, 0, 0, 0, 0, 0])
        for i in range(min(len(miner_hr_stats), len(node_hr_stats))):
            miner_hr_stats[i] += node_hr_stats[i]
    
    aggregated["miner_hashrate_stats"] = miner_hr_stats
    
    return aggregated

def get_aggregated_stats_cached(address=None, force_refresh=False):
    """Get aggregated stats with caching (30 second cache)"""
    with stats_lock:
        now = time.time()
        
        # Check if we need to refresh (cache expired or forced)
        if force_refresh or not stats_cache["data"] or (now - stats_cache["timestamp"]) > 30:
            # Fetch from all nodes concurrently
            node_stats = []
            
            with ThreadPoolExecutor(max_workers=len(POOL_NODES)) as executor:
                future_to_node = {
                    executor.submit(fetch_node_stats, node, address): node 
                    for node in POOL_NODES
                }
                
                for future in as_completed(future_to_node):
                    node_url = future_to_node[future]
                    try:
                        stats = future.result()
                        if stats:
                            node_stats.append(stats)
                    except Exception as e:
                        logger.error(f"Error fetching from {node_url}: {e}")
            
            if node_stats:
                aggregated = aggregate_pool_stats(node_stats, address)
                if not address:  # Only cache pool-wide stats, not miner-specific
                    stats_cache["data"] = aggregated
                    stats_cache["timestamp"] = now
                return aggregated
            else:
                logger.error("Failed to fetch stats from any nodes")
                return stats_cache["data"]  # Return cached data if available
        
        return stats_cache["data"]

def parse_redis_timeseries(data):
    """Parse Redis sorted set data into timestamps and values"""
    result = []
    for item in data:
        try:
            timestamp_str, value_str = item.split(':', 1)
            timestamp = int(timestamp_str)
            value = float(value_str)
            result.append([timestamp, value])
        except (ValueError, IndexError):
            continue
    return result

def get_time_range(hours=8):
    """Get timestamp range for the last N hours"""
    now = int(time.time())
    start = now - (hours * 3600)
    return start, now

@app.route('/api/health')
def health_check():
    """Health check endpoint"""
    try:
        r.ping()
        
        # Check how many nodes are responding
        responding_nodes = 0
        for node in POOL_NODES:
            try:
                response = requests.get(f'{node}/stats', timeout=2)
                if response.status_code == 200:
                    responding_nodes += 1
            except:
                pass
        
        return jsonify({
            "status": "healthy", 
            "redis": "connected",
            "pool_nodes": {
                "total": len(POOL_NODES),
                "responding": responding_nodes,
                "nodes": POOL_NODES
            }
        })
    except:
        return jsonify({"status": "unhealthy", "redis": "disconnected"}), 500

@app.route('/api/stats')
def get_current_stats():
    """Get current aggregated pool statistics"""
    try:
        # Check if address is provided
        address = request.args.get('address') or request.cookies.get('wa')
        
        if address:
            # For miner-specific requests, query nodes in real-time
            return get_miner_stats(address)
        else:
            # For pool stats, use Redis cache first, then fallback to live data
            try:
                redis_stats = r.get('pool:latest_stats')
                if redis_stats:
                    stats_data = json.loads(redis_stats)
                    stats_data['source'] = 'redis_cache'
                    return jsonify(stats_data)
            except Exception as e:
                logger.warning(f"Redis cache unavailable: {e}")
            
            # Fallback to live aggregated stats
            stats = get_aggregated_stats_cached()
            if stats:
                stats['source'] = 'live_aggregated'
                return jsonify(stats)
            else:
                return jsonify({"error": "No stats available from any pool nodes"}), 503
                
    except Exception as e:
        logger.error(f"Error fetching current stats: {e}")
        return jsonify({"error": "Failed to fetch stats"}), 500

def get_miner_stats(address):
    """Get miner-specific stats by querying all nodes in real-time"""
    try:
        # Start with pool stats from Redis/cache
        try:
            redis_stats = r.get('pool:latest_stats')
            if redis_stats:
                pool_data = json.loads(redis_stats)
            else:
                pool_data = get_aggregated_stats_cached() or {}
        except:
            pool_data = get_aggregated_stats_cached() or {}
        
        # Query all nodes for miner-specific data
        total_miner_hashrate = 0
        total_miner_balance = 0
        total_worker_count = 0
        miner_hr_stats = [0, 0, 0, 0, 0, 0]
        found_on_nodes = []
        
        with ThreadPoolExecutor(max_workers=len(POOL_NODES)) as executor:
            future_to_node = {
                executor.submit(fetch_node_stats, node, address): node 
                for node in POOL_NODES
            }
            
            for future in as_completed(future_to_node):
                node_url = future_to_node[future]
                try:
                    stats = future.result()
                    if stats and (stats.get('miner_hashrate', 0) > 0 or 
                                stats.get('miner_balance', 0) > 0 or 
                                stats.get('worker_count', 0) > 0):
                        
                        total_miner_hashrate += stats.get('miner_hashrate', 0)
                        total_miner_balance += stats.get('miner_balance', 0)
                        total_worker_count += stats.get('worker_count', 0)
                        
                        # Aggregate hashrate stats arrays
                        node_hr_stats = stats.get('miner_hashrate_stats', [0, 0, 0, 0, 0, 0])
                        for i in range(min(len(miner_hr_stats), len(node_hr_stats))):
                            miner_hr_stats[i] += node_hr_stats[i]
                        
                        found_on_nodes.append(node_url)
                        
                except Exception as e:
                    logger.error(f"Error fetching miner stats from {node_url}: {e}")
        
        # If no miner data found, return error
        if total_miner_hashrate == 0 and total_miner_balance == 0 and total_worker_count == 0:
            return jsonify({"error": "Miner not found"}), 404
        
        # Combine pool stats with miner stats
        result = pool_data.copy()
        result.update({
            "miner_hashrate": total_miner_hashrate,
            "miner_balance": total_miner_balance,
            "worker_count": total_worker_count,
            "miner_hashrate_stats": miner_hr_stats,
            "found_on_nodes": found_on_nodes,
            "source": "live_miner_query"
        })
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error fetching miner stats: {e}")
        return jsonify({"error": "Failed to fetch miner stats"}), 500

@app.route('/api/workers')
def get_workers():
    """Get workers for an address from all nodes"""
    try:
        address = request.args.get('address') or request.cookies.get('wa')
        
        if not address:
            return jsonify({"error": "No address provided"}), 400
        
        all_workers = []
        
        # Fetch workers from all nodes concurrently
        with ThreadPoolExecutor(max_workers=len(POOL_NODES)) as executor:
            future_to_node = {
                executor.submit(fetch_node_workers, node, address): node 
                for node in POOL_NODES
            }
            
            for future in as_completed(future_to_node):
                node_url = future_to_node[future]
                try:
                    workers = future.result()
                    if workers:
                        all_workers.extend(workers)
                except Exception as e:
                    logger.error(f"Error fetching workers from {node_url}: {e}")
        
        return jsonify(all_workers)
        
    except Exception as e:
        logger.error(f"Error fetching workers: {e}")
        return jsonify({"error": "Failed to fetch workers"}), 500

@app.route('/api/nodes')
def get_nodes_status():
    """Get status of all pool nodes"""
    try:
        nodes_status = []
        
        with ThreadPoolExecutor(max_workers=len(POOL_NODES)) as executor:
            future_to_node = {
                executor.submit(fetch_node_stats, node): node 
                for node in POOL_NODES
            }
            
            for future in as_completed(future_to_node):
                node_url = future_to_node[future]
                try:
                    stats = future.result()
                    if stats:
                        nodes_status.append({
                            "url": node_url,
                            "status": "online",
                            "hashrate": stats.get("pool_hashrate", 0),
                            "miners": stats.get("connected_miners", 0),
                            "blocks_found": stats.get("pool_blocks_found", 0),
                            "last_seen": int(time.time())
                        })
                    else:
                        nodes_status.append({
                            "url": node_url,
                            "status": "offline",
                            "hashrate": 0,
                            "miners": 0,
                            "blocks_found": 0,
                            "last_seen": 0
                        })
                except Exception as e:
                    nodes_status.append({
                        "url": node_url,
                        "status": "error",
                        "error": str(e),
                        "hashrate": 0,
                        "miners": 0,
                        "blocks_found": 0,
                        "last_seen": 0
                    })
        
        return jsonify(nodes_status)
        
    except Exception as e:
        logger.error(f"Error fetching nodes status: {e}")
        return jsonify({"error": "Failed to fetch nodes status"}), 500

# Keep your existing chart endpoints...
@app.route('/api/charts')
def get_chart_data():
    """Get chart data for the specified time range"""
    try:
        hours = int(request.args.get('hours', 8))
        start_time, end_time = get_time_range(hours)
        chart_type = request.args.get('type', 'all')
        address = request.args.get('address', '')
        
        chart_data = {}
        
        if chart_type in ['all', 'network']:
            network_data = r.zrangebyscore('network:hashrate', start_time, end_time)
            chart_data['network_hashrate'] = parse_redis_timeseries(network_data)
            
            difficulty_data = r.zrangebyscore('network:difficulty', start_time, end_time)
            chart_data['network_difficulty'] = parse_redis_timeseries(difficulty_data)
        
        if chart_type in ['all', 'pool']:
            pool_data = r.zrangebyscore('pool:hashrate', start_time, end_time)
            chart_data['pool_hashrate'] = parse_redis_timeseries(pool_data)
            
            effort_data = r.zrangebyscore('pool:effort', start_time, end_time)
            chart_data['pool_effort'] = parse_redis_timeseries(effort_data)
            
            miners_data = r.zrangebyscore('pool:miners', start_time, end_time)
            chart_data['pool_miners'] = parse_redis_timeseries(miners_data)
        
        if chart_type in ['all', 'miner'] and address:
            miner_data = r.zrangebyscore(f'miner:{address}:hashrate', start_time, end_time)
            chart_data['miner_hashrate'] = parse_redis_timeseries(miner_data)
            
            balance_data = r.zrangebyscore(f'miner:{address}:balance', start_time, end_time)
            chart_data['miner_balance'] = parse_redis_timeseries(balance_data)
        
        return jsonify(chart_data)
        
    except Exception as e:
        logger.error(f"Error fetching chart data: {e}")
        return jsonify({"error": "Failed to fetch chart data"}), 500

@app.route('/api/blocks')
def get_blocks_history():
    """Get blocks history with detailed information"""
    try:
        hours = int(request.args.get('hours', 24))
        start_time, end_time = get_time_range(hours)
        
        blocks_detailed = r.zrangebyscore('pool:blocks_detailed', start_time, end_time)
        
        if blocks_detailed:
            blocks = []
            for block_data in blocks_detailed:
                try:
                    block = json.loads(block_data.split(':', 1)[1])
                    blocks.append(block)
                except:
                    continue
            return jsonify(blocks)
        else:
            blocks_data = r.zrangebyscore('pool:blocks', start_time, end_time)
            blocks_timeline = parse_redis_timeseries(blocks_data)
            
            blocks = []
            for timestamp, height in blocks_timeline:
                blocks.append({
                    "ts": int(timestamp),
                    "height": int(height),
                    "reward": 20.0,
                    "hash": "",
                    "difficulty": 0
                })
            
            return jsonify(blocks)
        
    except Exception as e:
        logger.error(f"Error fetching blocks data: {e}")
        return jsonify({"error": "Failed to fetch blocks data"}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    print(f"Starting Salvium Pool Aggregated API Server on port {API_PORT}")
    print(f"Pool nodes: {POOL_NODES}")
    print(f"Endpoints available:")
    print(f"  GET /api/health - Health check")
    print(f"  GET /api/stats - Aggregated pool stats")
    print(f"  GET /api/workers - Workers from all nodes")
    print(f"  GET /api/nodes - Node status")
    print(f"  GET /api/charts - Chart data")
    print(f"  GET /api/blocks - Blocks history")
    
    app.run(host='127.0.0.1', port=API_PORT, debug=False)


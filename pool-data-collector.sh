#!/bin/bash
# pool-data-collector.sh - Collect pool stats from multiple nodes and store in Redis

# Configuration
POOL_NODES=("core.supportsal.com:4243" "node1.supportsal.com:4243")
REDIS_HOST="localhost"
REDIS_PORT="6379"
REDIS_DB="0"
TTL=259200  # 3 days in seconds

# Timestamp for this collection
TIMESTAMP=$(date +%s)

# Function to log with timestamp
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1"
}

# Function to store data in Redis with TTL
store_data() {
    local key="$1"
    local value="$2"
    
    # Store the data point
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -n "$REDIS_DB" \
        ZADD "$key" "$TIMESTAMP" "$TIMESTAMP:$value" >/dev/null
    
    # Set TTL on the sorted set
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -n "$REDIS_DB" \
        EXPIRE "$key" "$TTL" >/dev/null
    
    # Clean old entries (keep last 3 days)
    local cutoff=$((TIMESTAMP - TTL))
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -n "$REDIS_DB" \
        ZREMRANGEBYSCORE "$key" "-inf" "$cutoff" >/dev/null
}

# Function to collect and aggregate stats from all nodes
collect_aggregated_stats() {
    log "Collecting stats from all nodes..."
    
    local total_pool_hashrate=0
    local total_connected_miners=0
    local total_round_hashes=0
    local total_pool_blocks=0
    local max_last_template=0
    local max_last_block=0
    local network_hashrate=0
    local network_difficulty=0
    local network_height=0
    
    local active_nodes=0
    local node_stats=""
    local upstream_node=""
    local downstream_nodes=()
    
    # Collect from each node and determine which is upstream
    for node in "${POOL_NODES[@]}"; do
        log "Querying node: $node"
        
        local stats_json=$(curl -s "http://$node/stats" --connect-timeout 5 --max-time 10)
        
        if [ $? -eq 0 ] && [ -n "$stats_json" ] && [ "$stats_json" != "null" ]; then
            active_nodes=$((active_nodes + 1))
            
            # Parse node stats
            local node_pool_hr=$(echo "$stats_json" | jq -r '.pool_hashrate // 0')
            local node_miners=$(echo "$stats_json" | jq -r '.connected_miners // 0')
            local node_round_hashes=$(echo "$stats_json" | jq -r '.round_hashes // 0')
            local node_blocks=$(echo "$stats_json" | jq -r '.pool_blocks_found // 0')
            local node_last_template=$(echo "$stats_json" | jq -r '.last_template_fetched // 0')
            local node_last_block=$(echo "$stats_json" | jq -r '.last_block_found // 0')
            
            # Network stats (should be same across nodes, use latest)
            network_hashrate=$(echo "$stats_json" | jq -r '.network_hashrate // 0')
            network_difficulty=$(echo "$stats_json" | jq -r '.network_difficulty // 0')
            network_height=$(echo "$stats_json" | jq -r '.network_height // 0')
            
            # Detect upstream node (core.supportsal.com is our upstream)
            if [[ "$node" == *"core.supportsal.com"* ]]; then
                upstream_node="$node"
                # For upstream, use its aggregated totals (it receives data from downstreams)
                total_pool_hashrate="$node_pool_hr"
                total_connected_miners="$node_miners"
                total_round_hashes="$node_round_hashes"
                total_pool_blocks="$node_blocks"
                log "Upstream node $node: hr=$node_pool_hr, miners=$node_miners (using as totals)"
            else
                downstream_nodes+=("$node")
                log "Downstream node $node: hr=$node_pool_hr, miners=$node_miners (for reference only)"
            fi
            
            # Track maximums
            [ "$node_last_template" -gt "$max_last_template" ] && max_last_template="$node_last_template"
            [ "$node_last_block" -gt "$max_last_block" ] && max_last_block="$node_last_block"
            
            # Build node info for storage
            node_stats="$node_stats{\"url\":\"$node\",\"hashrate\":$node_pool_hr,\"miners\":$node_miners},"
        else
            log "WARNING: Failed to fetch stats from node: $node"
        fi
    done
    
    # If no upstream node found, fall back to summing all nodes (standalone setup)
    if [ -z "$upstream_node" ]; then
        log "No upstream node detected, summing all nodes"
        total_pool_hashrate=0
        total_connected_miners=0
        total_round_hashes=0
        total_pool_blocks=0
        
        for node in "${POOL_NODES[@]}"; do
            local stats_json=$(curl -s "http://$node/stats" --connect-timeout 5 --max-time 10)
            if [ $? -eq 0 ] && [ -n "$stats_json" ] && [ "$stats_json" != "null" ]; then
                local node_pool_hr=$(echo "$stats_json" | jq -r '.pool_hashrate // 0')
                local node_miners=$(echo "$stats_json" | jq -r '.connected_miners // 0')
                local node_round_hashes=$(echo "$stats_json" | jq -r '.round_hashes // 0')
                local node_blocks=$(echo "$stats_json" | jq -r '.pool_blocks_found // 0')
                
                total_pool_hashrate=$((total_pool_hashrate + node_pool_hr))
                total_connected_miners=$((total_connected_miners + node_miners))
                total_round_hashes=$((total_round_hashes + node_round_hashes))
                total_pool_blocks=$((total_pool_blocks + node_blocks))
            fi
        done
    fi
    
    # Remove trailing comma from node_stats
    node_stats="${node_stats%,}"
    
    if [ "$active_nodes" -eq 0 ]; then
        log "ERROR: No nodes responded"
        return 1
    fi
    
    log "Aggregated stats: total_hr=$total_pool_hashrate, total_miners=$total_connected_miners, active_nodes=$active_nodes"
    
    # Store aggregated data
    store_data "pool:hashrate" "$total_pool_hashrate"
    store_data "network:hashrate" "$network_hashrate"
    store_data "network:difficulty" "$network_difficulty"
    store_data "network:height" "$network_height"
    store_data "pool:miners" "$total_connected_miners"
    store_data "pool:blocks" "$total_pool_blocks"
    store_data "pool:round_hashes" "$total_round_hashes"
    
    # Calculate and store effort
    if [ "$network_difficulty" -gt 0 ] && [ "$total_round_hashes" -gt 0 ]; then
        local effort=$(echo "scale=2; ($total_round_hashes * 100) / $network_difficulty" | bc -l)
        store_data "pool:effort" "$effort"
    fi
    
    # Store aggregated JSON for the API
    local aggregated_json=$(cat <<EOF
{
    "pool_hashrate": $total_pool_hashrate,
    "network_hashrate": $network_hashrate,
    "network_difficulty": $network_difficulty,
    "network_height": $network_height,
    "connected_miners": $total_connected_miners,
    "pool_blocks_found": $total_pool_blocks,
    "round_hashes": $total_round_hashes,
    "last_template_fetched": $max_last_template,
    "last_block_found": $max_last_block,
    "active_nodes": $active_nodes,
    "total_nodes": ${#POOL_NODES[@]},
    "timestamp": $TIMESTAMP,
    "nodes_info": [$node_stats]
}
EOF
)
    
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -n "$REDIS_DB" \
        SET "pool:latest_stats" "$aggregated_json" EX 300 >/dev/null
}

# Function to collect miner stats from all nodes (REMOVED - handled dynamically by API)
# collect_miner_stats() {
#     # This function removed - miner stats now handled dynamically by the Python API
#     log "Miner stats collection handled dynamically by API service"
# }

# Main execution
main() {
    log "Starting multi-node data collection cycle..."
    
    # Check if required tools are available
    for tool in jq redis-cli bc curl; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            log "ERROR: $tool is required but not installed"
            exit 1
        fi
    done
    
    # Test Redis connection
    if ! redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -n "$REDIS_DB" ping >/dev/null 2>&1; then
        log "ERROR: Cannot connect to Redis at $REDIS_HOST:$REDIS_PORT"
        exit 1
    fi
    
    # Collect aggregated data
    collect_aggregated_stats
    
    log "Data collection cycle completed (miner stats handled dynamically by API)"
}

# Handle script arguments
case "${1:-}" in
    "pool-only")
        collect_aggregated_stats
        ;;
    "miners-only")
        collect_miner_stats
        ;;
    *)
        main
        ;;
esac


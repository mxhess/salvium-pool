#!/usr/bin/env python3

'''
LMDB Pool Database Cleanup Tool
Cleans old records from monero-pool LMDB database

Based on the database structure from jtgrassie/monero-pool
'''

import argparse
import lmdb
import os
import sys
from ctypes import *
from datetime import datetime, timedelta
import time

class share_t(Structure):
    _fields_ = [('height', c_longlong),
                ('difficulty', c_longlong),
                ('address', c_char*128),
                ('timestamp', c_longlong)]

class payment_t(Structure):
    _fields_ = [('amount', c_longlong),
                ('timestamp', c_longlong),
                ('address', c_char*128)]

class block_t(Structure):
    _fields_ = [('height', c_longlong),
                ('hash', c_char*64),
                ('prev_hash', c_char*64),
                ('difficulty', c_longlong),
                ('status', c_long),
                ('reward', c_longlong),
                ('timestamp', c_longlong)]

def format_timestamp(timestamp):
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime('%Y-%m-%d %H:%M:%S')

def format_amount(amount):
    return '{0:.6f}'.format(amount/1e12)

def format_address(address):
    if isinstance(address, bytes):
        address = address.decode('utf-8').rstrip('\0')
    return '{}...{}'.format(address[:8], address[-8:])

def address_from_key(key):
    return key.decode('utf-8').rstrip('\0')

def get_database_stats(db_path, verbose=False):
    """Get statistics about database contents"""
    if not os.path.exists(db_path):
        print(f"Error: Database path {db_path} does not exist")
        return None
    
    try:
        env = lmdb.open(db_path, readonly=True, max_dbs=10, create=False)
        stats = {}
        
        # Check each database
        db_names = ['shares', 'payments', 'blocks', 'balance']
        
        for db_name in db_names:
            try:
                db = env.open_db(db_name.encode(), dupsort=(db_name == 'shares'))
                with env.begin(db=db) as txn:
                    stat = txn.stat(db)
                    stats[db_name] = {
                        'entries': stat['entries'],
                        'branch_pages': stat['branch_pages'],
                        'leaf_pages': stat['leaf_pages'],
                        'overflow_pages': stat['overflow_pages']
                    }
                    
                    if verbose:
                        print(f"\n{db_name.upper()} DATABASE:")
                        print(f"  Entries: {stat['entries']:,}")
                        print(f"  Branch pages: {stat['branch_pages']:,}")
                        print(f"  Leaf pages: {stat['leaf_pages']:,}")
                        print(f"  Overflow pages: {stat['overflow_pages']:,}")
                        
            except lmdb.NotFoundError:
                if verbose:
                    print(f"{db_name} database not found")
                stats[db_name] = {'entries': 0}
        
        env.close()
        return stats
        
    except Exception as e:
        print(f"Error reading database: {e}")
        return None

def cleanup_shares(db_path, cutoff_time, dry_run=True, verbose=False):
    """Clean up old shares based on timestamp"""
    deleted_count = 0
    scanned_count = 0
    
    if verbose:
        print(f"\nCleaning shares older than {format_timestamp(cutoff_time)}")
    
    try:
        # Open in read-write mode if not dry run
        env = lmdb.open(db_path, readonly=dry_run, max_dbs=10, create=False)
        shares_db = env.open_db('shares'.encode(), dupsort=True)
        
        with env.begin(db=shares_db, write=not dry_run) as txn:
            with txn.cursor() as cursor:
                cursor.first()
                keys_to_delete = []
                
                while cursor.next():
                    scanned_count += 1
                    key, value = cursor.item()
                    
                    try:
                        share = share_t.from_buffer_copy(value)
                        if share.timestamp < cutoff_time:
                            keys_to_delete.append((key, value))
                            deleted_count += 1
                            
                            if verbose and deleted_count % 10000 == 0:
                                print(f"  Found {deleted_count} old shares so far...")
                                
                    except Exception as e:
                        if verbose:
                            print(f"  Warning: Could not parse share record: {e}")
                        continue
                
                # Delete the records if not dry run
                if not dry_run and keys_to_delete:
                    if verbose:
                        print(f"  Deleting {len(keys_to_delete)} share records...")
                    
                    for key, value in keys_to_delete:
                        cursor.set_key_dup(key, value)
                        cursor.delete()
        
        env.close()
        
    except Exception as e:
        print(f"Error cleaning shares: {e}")
        return 0, 0
    
    return scanned_count, deleted_count

def cleanup_payments(db_path, cutoff_time, dry_run=True, verbose=False):
    """Clean up old payment records based on timestamp"""
    deleted_count = 0
    scanned_count = 0
    
    if verbose:
        print(f"\nCleaning payments older than {format_timestamp(cutoff_time)}")
    
    try:
        env = lmdb.open(db_path, readonly=dry_run, max_dbs=10, create=False)
        payments_db = env.open_db('payments'.encode())
        
        with env.begin(db=payments_db, write=not dry_run) as txn:
            with txn.cursor() as cursor:
                cursor.first()
                keys_to_delete = []
                
                while True:
                    try:
                        key, value = cursor.item()
                        scanned_count += 1
                        
                        payment = payment_t.from_buffer_copy(value)
                        if payment.timestamp < cutoff_time:
                            keys_to_delete.append(key)
                            deleted_count += 1
                            
                            if verbose and deleted_count % 1000 == 0:
                                print(f"  Found {deleted_count} old payments so far...")
                        
                        if not cursor.next():
                            break
                            
                    except Exception as e:
                        if verbose:
                            print(f"  Warning: Could not parse payment record: {e}")
                        if not cursor.next():
                            break
                        continue
                
                # Delete the records if not dry run
                if not dry_run and keys_to_delete:
                    if verbose:
                        print(f"  Deleting {len(keys_to_delete)} payment records...")
                    
                    for key in keys_to_delete:
                        cursor.set_key(key)
                        cursor.delete()
        
        env.close()
        
    except Exception as e:
        print(f"Error cleaning payments: {e}")
        return 0, 0
    
    return scanned_count, deleted_count

def cleanup_blocks(db_path, cutoff_time, dry_run=True, verbose=False, keep_unlocked=True):
    """Clean up old block records, optionally keeping unlocked blocks"""
    deleted_count = 0
    scanned_count = 0
    
    if verbose:
        print(f"\nCleaning blocks older than {format_timestamp(cutoff_time)}")
        if keep_unlocked:
            print("  (keeping unlocked blocks regardless of age)")
    
    try:
        env = lmdb.open(db_path, readonly=dry_run, max_dbs=10, create=False)
        blocks_db = env.open_db('blocks'.encode())
        
        with env.begin(db=blocks_db, write=not dry_run) as txn:
            with txn.cursor() as cursor:
                cursor.first()
                keys_to_delete = []
                
                while True:
                    try:
                        key, value = cursor.item()
                        scanned_count += 1
                        
                        block = block_t.from_buffer_copy(value)
                        
                        # Check if block should be deleted
                        should_delete = block.timestamp < cutoff_time
                        
                        # Keep unlocked blocks if requested (status 1 = UNLOCKED)
                        if keep_unlocked and block.status == 1:
                            should_delete = False
                        
                        if should_delete:
                            keys_to_delete.append(key)
                            deleted_count += 1
                            
                            if verbose:
                                height = c_longlong.from_buffer_copy(key).value
                                status_names = ["LOCKED", "UNLOCKED", "ORPHANED"]
                                status = status_names[block.status] if block.status < len(status_names) else "UNKNOWN"
                                print(f"  Will delete block {height} ({status}, {format_timestamp(block.timestamp)})")
                        
                        if not cursor.next():
                            break
                            
                    except Exception as e:
                        if verbose:
                            print(f"  Warning: Could not parse block record: {e}")
                        if not cursor.next():
                            break
                        continue
                
                # Delete the records if not dry run
                if not dry_run and keys_to_delete:
                    if verbose:
                        print(f"  Deleting {len(keys_to_delete)} block records...")
                    
                    for key in keys_to_delete:
                        cursor.set_key(key)
                        cursor.delete()
        
        env.close()
        
    except Exception as e:
        print(f"Error cleaning blocks: {e}")
        return 0, 0
    
    return scanned_count, deleted_count

def cleanup_zero_balances(db_path, dry_run=True, verbose=False):
    """Clean up zero balance entries"""
    deleted_count = 0
    scanned_count = 0
    
    if verbose:
        print(f"\nCleaning zero balances")
    
    try:
        env = lmdb.open(db_path, readonly=dry_run, max_dbs=10, create=False)
        balance_db = env.open_db('balance'.encode())
        
        with env.begin(db=balance_db, write=not dry_run) as txn:
            with txn.cursor() as cursor:
                cursor.first()
                keys_to_delete = []
                
                while True:
                    try:
                        key, value = cursor.item()
                        scanned_count += 1
                        
                        amount = c_longlong.from_buffer_copy(value).value
                        if amount == 0:
                            keys_to_delete.append(key)
                            deleted_count += 1
                            
                            if verbose:
                                address = format_address(address_from_key(key))
                                print(f"  Will delete zero balance for {address}")
                        
                        if not cursor.next():
                            break
                            
                    except Exception as e:
                        if verbose:
                            print(f"  Warning: Could not parse balance record: {e}")
                        if not cursor.next():
                            break
                        continue
                
                # Delete the records if not dry run
                if not dry_run and keys_to_delete:
                    if verbose:
                        print(f"  Deleting {len(keys_to_delete)} zero balance records...")
                    
                    for key in keys_to_delete:
                        cursor.set_key(key)
                        cursor.delete()
        
        env.close()
        
    except Exception as e:
        print(f"Error cleaning balances: {e}")
        return 0, 0
    
    return scanned_count, deleted_count

def cleanup_dust_balances(db_path, cutoff_time, dust_threshold, pool_wallet, dry_run=True, verbose=False):
    """Sweep dust balances from inactive miners to pool wallet"""
    cleaned_count = 0
    scanned_count = 0
    total_dust_swept = 0
    
    if verbose:
        print(f"\nSweeping dust balances from miners inactive since {format_timestamp(cutoff_time)}")
        print(f"Dust threshold: {format_amount(dust_threshold)} XMR")
        print(f"Pool wallet: {format_address(pool_wallet)}")
    
    try:
        # Step 1: Find last activity time for each miner from shares
        if verbose:
            print("  Scanning shares for miner activity...")
        
        env = lmdb.open(db_path, readonly=True, max_dbs=10, create=False)
        shares_db = env.open_db('shares'.encode(), dupsort=True)
        miner_last_activity = {}
        
        with env.begin(db=shares_db) as txn:
            with txn.cursor() as cursor:
                cursor.first()
                shares_scanned = 0
                
                while True:
                    try:
                        key, value = cursor.item()
                        share = share_t.from_buffer_copy(value)
                        address = share.address.decode('utf-8').rstrip('\0')
                        
                        # Track the latest activity for each miner
                        miner_last_activity[address] = max(
                            miner_last_activity.get(address, 0), 
                            share.timestamp
                        )
                        
                        shares_scanned += 1
                        if verbose and shares_scanned % 50000 == 0:
                            print(f"    Scanned {shares_scanned:,} shares, tracking {len(miner_last_activity):,} miners...")
                        
                        if not cursor.next():
                            break
                            
                    except Exception as e:
                        if verbose:
                            print(f"    Warning: Could not parse share record: {e}")
                        if not cursor.next():
                            break
                        continue
        
        env.close()
        
        if verbose:
            print(f"  Found activity data for {len(miner_last_activity):,} miners")
        
        # Step 2: Check balances and identify dust from inactive miners
        if verbose:
            print("  Scanning balances for inactive dust...")
        
        env = lmdb.open(db_path, readonly=dry_run, max_dbs=10, create=False)
        balance_db = env.open_db('balance'.encode())
        
        dust_to_sweep = []
        pool_balance_increase = 0
        
        with env.begin(db=balance_db, write=not dry_run) as txn:
            with txn.cursor() as cursor:
                cursor.first()
                
                while True:
                    try:
                        key, value = cursor.item()
                        scanned_count += 1
                        
                        address = address_from_key(key)
                        amount = c_longlong.from_buffer_copy(value).value
                        
                        # Skip if no balance or if it's the pool wallet
                        if amount <= 0 or address == pool_wallet:
                            if not cursor.next():
                                break
                            continue
                        
                        # Check if this is dust (below threshold)
                        if amount < dust_threshold:
                            # Check if miner has been inactive
                            last_activity = miner_last_activity.get(address, 0)
                            
                            if last_activity < cutoff_time:
                                dust_to_sweep.append((key, address, amount, last_activity))
                                total_dust_swept += amount
                                cleaned_count += 1
                                
                                if verbose:
                                    last_activity_str = format_timestamp(last_activity) if last_activity > 0 else "Never"
                                    print(f"    {format_address(address)}: {format_amount(amount)} XMR (last active: {last_activity_str})")
                        
                        if not cursor.next():
                            break
                            
                    except Exception as e:
                        if verbose:
                            print(f"    Warning: Could not parse balance record: {e}")
                        if not cursor.next():
                            break
                        continue
                
                # Perform the sweep if not dry run
                if not dry_run and dust_to_sweep:
                    if verbose:
                        print(f"  Sweeping {len(dust_to_sweep)} dust balances...")
                    
                    # Add dust to pool wallet balance
                    pool_key = pool_wallet.encode('utf-8')
                    try:
                        cursor.set_key(pool_key)
                        _, pool_value = cursor.item()
                        current_pool_balance = c_longlong.from_buffer_copy(pool_value).value
                    except lmdb.NotFoundError:
                        current_pool_balance = 0
                    
                    new_pool_balance = current_pool_balance + total_dust_swept
                    new_pool_value = c_longlong(new_pool_balance)
                    
                    # Update pool wallet balance
                    cursor.set_key(pool_key)
                    if current_pool_balance > 0:
                        cursor.replace(new_pool_value)
                    else:
                        cursor.put(pool_key, new_pool_value)
                    
                    # Remove dust balances
                    for key, address, amount, last_activity in dust_to_sweep:
                        cursor.set_key(key)
                        cursor.delete()
                    
                    if verbose:
                        print(f"  Pool wallet balance increased by {format_amount(total_dust_swept)} XMR")
        
        env.close()
        
    except Exception as e:
        print(f"Error sweeping dust balances: {e}")
        return 0, 0, 0
    
    return scanned_count, cleaned_count, total_dust_swept

def main():
    parser = argparse.ArgumentParser(description='Clean up old records from monero-pool LMDB database')
    parser.add_argument('database', help='Path to LMDB database directory')
    parser.add_argument('-r', '--retention-days', type=int, default=365,
                       help='Number of days to retain data (default: 365)')
    parser.add_argument('-n', '--dry-run', action='store_true',
                       help='Show what would be deleted without actually deleting')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Enable verbose output')
    parser.add_argument('-f', '--force', action='store_true',
                       help='Skip confirmation prompt')
    parser.add_argument('--no-shares', action='store_true',
                       help='Skip cleaning shares')
    parser.add_argument('--no-payments', action='store_true',
                       help='Skip cleaning payments')
    parser.add_argument('--no-blocks', action='store_true',
                       help='Skip cleaning blocks')
    parser.add_argument('--no-balances', action='store_true',
                       help='Skip cleaning zero balances')
    parser.add_argument('--dust-balances', action='store_true',
                       help='Sweep dust balances from inactive miners to pool wallet')
    parser.add_argument('--dust-threshold', type=float, default=0.1,
                       help='Dust threshold in XMR (default: 0.1)')
    parser.add_argument('--pool-wallet', type=str,
                       help='Pool wallet address to receive swept dust (required with --dust-balances)')
    parser.add_argument('--keep-unlocked-blocks', action='store_true', default=True,
                       help='Keep unlocked blocks regardless of age (default: true)')
    parser.add_argument('--stats-only', action='store_true',
                       help='Only show database statistics, no cleanup')
    
    args = parser.parse_args()
    
    # Validate dust balance arguments
    if args.dust_balances and not args.pool_wallet:
        print("Error: --pool-wallet is required when using --dust-balances")
        sys.exit(1)
    
    if not os.path.exists(args.database):
        print(f"Error: Database path {args.database} does not exist")
        sys.exit(1)
    
    # Calculate cutoff time
    cutoff_date = datetime.now() - timedelta(days=args.retention_days)
    cutoff_time = int(cutoff_date.timestamp())
    
    print(f"LMDB Pool Database Cleanup Tool")
    print(f"Database: {args.database}")
    print(f"Retention: {args.retention_days} days")
    print(f"Cutoff date: {cutoff_date.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if args.dry_run:
        print("Mode: DRY RUN (no data will be deleted)")
    else:
        print("Mode: LIVE CLEANUP (data will be permanently deleted)")
    
    # Get initial stats
    print("\n=== INITIAL DATABASE STATISTICS ===")
    initial_stats = get_database_stats(args.database, args.verbose)
    if not initial_stats:
        sys.exit(1)
    
    for db_name, stats in initial_stats.items():
        if stats['entries'] > 0:
            print(f"{db_name}: {stats['entries']:,} entries")
    
    if args.stats_only:
        sys.exit(0)
    
    # Confirmation
    if not args.force and not args.dry_run:
        response = input(f"\nProceed with cleanup? [y/N]: ")
        if response.lower() != 'y':
            print("Aborted.")
            sys.exit(0)
    
    total_scanned = 0
    total_deleted = 0
    
    # Clean shares
    if not args.no_shares:
        try:
            scanned, deleted = cleanup_shares(args.database, cutoff_time, args.dry_run, args.verbose)
            total_scanned += scanned
            total_deleted += deleted
            print(f"\nShares: {scanned:,} scanned, {deleted:,} {'would be ' if args.dry_run else ''}deleted")
        except Exception as e:
            print(f"Error cleaning shares: {e}")
    
    # Clean payments
    if not args.no_payments:
        try:
            scanned, deleted = cleanup_payments(args.database, cutoff_time, args.dry_run, args.verbose)
            total_scanned += scanned
            total_deleted += deleted
            print(f"Payments: {scanned:,} scanned, {deleted:,} {'would be ' if args.dry_run else ''}deleted")
        except Exception as e:
            print(f"Error cleaning payments: {e}")
    
    # Clean blocks
    if not args.no_blocks:
        try:
            scanned, deleted = cleanup_blocks(args.database, cutoff_time, args.dry_run, args.verbose, args.keep_unlocked_blocks)
            total_scanned += scanned
            total_deleted += deleted
            print(f"Blocks: {scanned:,} scanned, {deleted:,} {'would be ' if args.dry_run else ''}deleted")
        except Exception as e:
            print(f"Error cleaning blocks: {e}")
    
    # Clean zero balances
    if not args.no_balances:
        try:
            scanned, deleted = cleanup_zero_balances(args.database, args.dry_run, args.verbose)
            total_scanned += scanned
            total_deleted += deleted
            print(f"Balances: {scanned:,} scanned, {deleted:,} zero balances {'would be ' if args.dry_run else ''}deleted")
        except Exception as e:
            print(f"Error cleaning balances: {e}")
    
    # Sweep dust balances from inactive miners
    if args.dust_balances:
        try:
            dust_threshold_atomic = int(args.dust_threshold * 1e12)  # Convert XMR to atomic units
            scanned, swept, total_dust = cleanup_dust_balances(
                args.database, cutoff_time, dust_threshold_atomic, 
                args.pool_wallet, args.dry_run, args.verbose
            )
            total_scanned += scanned
            print(f"Dust sweep: {scanned:,} balances scanned, {swept:,} inactive dust balances {'would be ' if args.dry_run else ''}swept")
            print(f"Total dust {'would be ' if args.dry_run else ''}swept: {format_amount(total_dust)} XMR")
        except Exception as e:
            print(f"Error sweeping dust balances: {e}")
    
    print(f"\n=== SUMMARY ===")
    print(f"Total records scanned: {total_scanned:,}")
    print(f"Total records {'would be ' if args.dry_run else ''}deleted: {total_deleted:,}")
    
    # Show final stats if not dry run
    if not args.dry_run and total_deleted > 0:
        print("\n=== FINAL DATABASE STATISTICS ===")
        final_stats = get_database_stats(args.database, False)
        if final_stats:
            for db_name, stats in final_stats.items():
                if stats['entries'] > 0:
                    initial_count = initial_stats.get(db_name, {}).get('entries', 0)
                    final_count = stats['entries']
                    saved = initial_count - final_count
                    print(f"{db_name}: {final_count:,} entries (saved {saved:,})")
    
    if args.dry_run:
        print(f"\nTo perform actual cleanup, run again without --dry-run")

if __name__ == '__main__':
    main()


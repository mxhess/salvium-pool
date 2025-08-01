// shared_template.h
#ifndef SHARED_TEMPLATE_H
#define SHARED_TEMPLATE_H

#include <pthread.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <semaphore.h>

// Shared memory structure for block templates
typedef struct {
    pthread_mutex_t lock;           // Mutex for thread-safe access
    uint64_t template_version;      // Incremented on each update
    uint64_t height;               // Block height
    uint64_t difficulty;           // Block difficulty
    char seed_hash[65];            // RandomX seed hash
    char next_seed_hash[65];       // Next seed hash
    char prev_hash[65];            // Previous block hash
    char *hashing_blob;            // Hashing blob data
    size_t hashing_blob_size;      // Size of hashing blob
    char *block_blob;              // Block blob data
    size_t block_blob_size;        // Size of block blob
    uint32_t reserved_offset;      // Reserved offset
    uint64_t tx_count;             // Transaction count
    time_t timestamp;              // When template was created
} shared_template_t;

// Global shared memory pointer
extern shared_template_t *shared_template;
extern uint64_t local_template_version;

// Function declarations
int shared_template_init(void);
void shared_template_cleanup(void);
int shared_template_update(const block_template_t *new_template);
int shared_template_get_latest(block_template_t *local_template);
bool shared_template_is_newer(void);

#endif // SHARED_TEMPLATE_H


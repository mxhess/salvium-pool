#ifndef SHARED_TEMPLATE_H
#define SHARED_TEMPLATE_H

#include <pthread.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdbool.h>
#include <stdint.h>
#include <time.h>

// Forward declaration (the actual struct is defined in pool.c)
typedef struct block_template_t block_template_t;

// Shared memory structure for block templates
typedef struct {
    pthread_mutex_t lock;
    uint64_t template_version;
    uint64_t height;
    uint64_t difficulty;
    char seed_hash[65];
    char next_seed_hash[65];
    char prev_hash[65];
    uint32_t reserved_offset;
    uint64_t tx_count;
    time_t timestamp;
    size_t hashing_blob_size;
} shared_template_t;

// Function declarations
int shared_template_init(void);
void shared_template_cleanup(void);
int shared_template_update(const block_template_t *new_template);
int shared_template_get_latest(block_template_t *local_template);
bool shared_template_is_newer(void);

#endif


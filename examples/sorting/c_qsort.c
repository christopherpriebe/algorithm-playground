/*
 * Reference C implementation of the sorting contract using qsort(3).
 *
 * Reads u64 element count + count int32 values from input_path, sorts them
 * ascending, and writes u64 + count int32 values to output_path. The
 * (optional) trace_path is ignored: this implementation demonstrates the
 * "trace not supported" fallback path in the playground's debug command.
 */

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int compare_int32(const void *left_pointer, const void *right_pointer)
{
    int32_t left = *(const int32_t *)left_pointer;
    int32_t right = *(const int32_t *)right_pointer;
    if (left < right)
        return -1;
    if (left > right)
        return 1;
    return 0;
}

static int read_input(const char *path, uint64_t *out_count, int32_t **out_values)
{
    FILE *stream = fopen(path, "rb");
    if (stream == NULL) {
        fprintf(stderr, "failed to open input '%s': %s\n", path, strerror(errno));
        return -1;
    }

    uint64_t count = 0;
    if (fread(&count, sizeof(count), 1, stream) != 1) {
        fprintf(stderr, "failed to read element count from '%s'\n", path);
        fclose(stream);
        return -1;
    }

    int32_t *values = NULL;
    if (count > 0) {
        values = (int32_t *)malloc((size_t)count * sizeof(int32_t));
        if (values == NULL) {
            fprintf(stderr, "failed to allocate %llu i32 elements\n",
                    (unsigned long long)count);
            fclose(stream);
            return -1;
        }
        if (fread(values, sizeof(int32_t), (size_t)count, stream) != (size_t)count) {
            fprintf(stderr, "failed to read %llu i32 elements from '%s'\n",
                    (unsigned long long)count, path);
            free(values);
            fclose(stream);
            return -1;
        }
    }

    fclose(stream);
    *out_count = count;
    *out_values = values;
    return 0;
}

static int write_output(const char *path, uint64_t count, const int32_t *values)
{
    FILE *stream = fopen(path, "wb");
    if (stream == NULL) {
        fprintf(stderr, "failed to open output '%s': %s\n", path, strerror(errno));
        return -1;
    }

    if (fwrite(&count, sizeof(count), 1, stream) != 1) {
        fprintf(stderr, "failed to write element count to '%s'\n", path);
        fclose(stream);
        return -1;
    }
    if (count > 0 && fwrite(values, sizeof(int32_t), (size_t)count, stream) != (size_t)count) {
        fprintf(stderr, "failed to write %llu i32 elements to '%s'\n",
                (unsigned long long)count, path);
        fclose(stream);
        return -1;
    }

    fclose(stream);
    return 0;
}

int main(int argument_count, char *arguments[])
{
    if (argument_count != 3 && argument_count != 4) {
        fprintf(stderr, "usage: %s <input.bin> <output.bin> [<trace.bin>]\n", arguments[0]);
        return 2;
    }

    uint64_t count = 0;
    int32_t *values = NULL;
    if (read_input(arguments[1], &count, &values) != 0)
        return 1;

    if (count > 0)
        qsort(values, (size_t)count, sizeof(int32_t), compare_int32);

    int status = write_output(arguments[2], count, values);
    free(values);

    /*
     * arguments[3] (trace_path) is intentionally ignored: this executable does
     * not implement the optional state-snapshot trace.
     */
    (void)argument_count;
    return status == 0 ? 0 : 1;
}

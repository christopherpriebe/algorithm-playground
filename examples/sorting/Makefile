CC      ?= cc
CFLAGS  ?= -O2 -Wall -Wextra -Wpedantic -std=c11

.PHONY: all clean

all: c_qsort

c_qsort: c_qsort.c
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f c_qsort

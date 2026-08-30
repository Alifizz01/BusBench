# Builds and runs the C half of the portfolio.
#
# Run this from a shell that has a POSIX sh: Git Bash, MSYS2, WSL, Linux or
# macOS. From a plain Windows prompt use the Python runner instead, which
# does the same job and finds an MSYS2 compiler on its own:
#
#     python run_all.py
#
# Each test binary is run from inside its own project directory, because
# several of them read data files with relative paths.

CC      ?= gcc
CFLAGS  ?= -std=c11 -Wall -Wextra -Iinclude
LDLIBS  ?= -lm
PYTHON  ?= python

# Project 5 needs Winsock on Windows. Ask the compiler what it targets
# rather than the shell what it is: the answer is right under Git Bash,
# MSYS2, WSL and a cross build alike.
ifneq (,$(findstring mingw,$(shell $(CC) -dumpmachine)))
  SOCKLIBS := -lws2_32
else
  SOCKLIBS :=
endif

P01 := 01-CAN-Bus-Sniffer-Decoder
P02 := 02-UDS-Diagnostic-Client
P03 := 03-AUTOSAR-Layered-ECU-Sim
P04 := 04-ISO26262-Safety-Watchdog
P05 := 05-DoIP-CAN-to-Ethernet-Gateway
P06 := 06-ARINC429-Bus-Analyzer
P07 := 07-MIL1553-Bus-Controller-Sim
P08 := 08-ARINC653-Partition-Scheduler
P09 := 09-DO178C-Traceability-Tool
P10 := 10-Flight-Data-Recorder

RUN_TARGETS := run-01 run-02 run-03 run-04 run-05 run-06 run-07 run-08 run-09 run-10

.PHONY: all test test-c test-py clean help $(RUN_TARGETS) server-05

all: test

help:
	@echo "make test      build and run everything, C and Python"
	@echo "make test-c    the C half only"
	@echo "make test-py   the Python half only"
	@echo "make run-NN    one project, e.g. make run-05"
	@echo "make server-05 start the DoIP gateway on port 13400"
	@echo "make clean     remove build output"

test: test-c test-py

test-c: $(RUN_TARGETS)

test-py:
	@for d in [0-9][0-9]-*; do \
	  for t in "$$d"/test/test_*.py; do \
	    [ -e "$$t" ] || continue; \
	    printf '%-34s ' "$$d"; \
	    ( cd "$$d" && $(PYTHON) "$${t#*/}" ) || exit 1; \
	  done; \
	done

# Each project compiles every src/*.c except files carrying their own main(),
# plus its test, into build/run_tests.
define build_and_run
	@mkdir -p $(1)/build
	@cd $(1) && $(CC) $(CFLAGS) $(2) test/$(3) -o build/run_tests $(LDLIBS) $(4)
	@echo "=== $(1) ==="
	@cd $(1) && ./build/run_tests
	@echo
endef

run-01:
	$(call build_and_run,$(P01),src/can_sniffer.c,test_can_sniffer.c,)

run-02:
	$(call build_and_run,$(P02),src/isotp.c src/uds_client.c src/ecu_sim.c,test_uds_client.c,)

run-03:
	$(call build_and_run,$(P03),src/rte.c src/bsw.c src/app_swc.c,test_rte.c,)

run-04:
	$(call build_and_run,$(P04),src/watchdog.c,test_watchdog.c,)

# server_main.c has its own main() and is left out of the test binary.
run-05:
	$(call build_and_run,$(P05),src/doip_gateway.c src/doip_server.c,test_doip.c,$(SOCKLIBS))

run-06:
	$(call build_and_run,$(P06),src/arinc429_analyzer.c,test_arinc429.c,)

run-07:
	$(call build_and_run,$(P07),src/mil1553_bc.c,test_mil1553.c,)

run-08:
	$(call build_and_run,$(P08),src/partition_sched.c,test_partition_sched.c,)

run-09:
	$(call build_and_run,$(P09),src/trace_tool.c,test_trace_tool.c,)

run-10:
	$(call build_and_run,$(P10),src/fdr_logger.c,test_fdr_logger.c,)

# The real gateway, listening on 127.0.0.1:13400. Drive it with the Python
# tester in 05-DoIP-CAN-to-Ethernet-Gateway/python/doip.py.
server-05:
	@mkdir -p $(P05)/build
	@cd $(P05) && $(CC) $(CFLAGS) src/*.c -o build/doip_server $(LDLIBS) $(SOCKLIBS)
	@cd $(P05) && ./build/doip_server

clean:
	@rm -rf [0-9][0-9]-*/build
	@rm -f [0-9][0-9]-*/trace_report.md [0-9][0-9]-*/*.bin
	@echo "cleaned"

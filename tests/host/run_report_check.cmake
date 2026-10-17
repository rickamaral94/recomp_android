# SPDX-License-Identifier: GPL-3.0-or-later
# Runs recomp-report and feeds its stdout to tools/check_report.py.
execute_process(COMMAND ${CLI} OUTPUT_FILE report_cli_output.json RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
    message(FATAL_ERROR "recomp-report exited with ${rc}")
endif()
execute_process(COMMAND ${PYTHON} -I ${CHECKER} report_cli_output.json RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
    message(FATAL_ERROR "check_report.py rejected the report")
endif()

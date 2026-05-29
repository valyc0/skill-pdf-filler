#!/bin/sh
# docker-entrypoint.sh — dispatcher interno al container
#
# "detect"     → detect_fields.py  (analisi campi PDF)
# qualsiasi altra cosa → pdf_filler_api.py  (API server)

if [ "$1" = "detect" ]; then
    shift
    exec python3 /app/detect_fields.py "$@"
else
    exec python3 /app/pdf_filler_api.py "$@"
fi

#!/bin/bash
DIR=$(dirname $0)
cd "${DIR}"
#export G15_PLUGINS=./src/plugins
if [ $# -eq 0 ]; then
  args=restart
else
  args=$@
fi
src/scripts/g15-desktop-service -f -l DEBUG $args

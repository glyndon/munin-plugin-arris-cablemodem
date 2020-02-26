#!/bin/bash

export MUNIN_CAP_DIRTYCONFIG=1
export MUNIN_PLUGSTATE=.
export MUNIN_STATEFILE=./statefile
#export MODEM_STATUS_URL=status8200.html
./arris.py config nospeedtest

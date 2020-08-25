#!/bin/sh
#list the drivers for the fat version
BLACKLIST='-e bfa -e csiostor -e cxgb4 -e bna -e aic94xx -e mlx4_core -e mlx4_en -e cxgb3'
KERNEL_VERSION=$1
set -e
find /lib/modules/$KERNEL_VERSION/kernel/drivers/net/ethernet /lib/modules/$KERNEL_VERSION/kernel/drivers/scsi -type f -printf '%f\n' | sed 's/\.ko.xz$//' | grep -v $BLACKLIST

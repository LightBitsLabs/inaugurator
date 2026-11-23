#!/bin/sh
#fails when the kernel and the initrd together are larger than the budget
#usage: check_image_size.sh <kernel> <initrd> <budget in bytes>
set -e
kernel=`stat -c %s "$1"`
initrd=`stat -c %s "$2"`
total=`expr $kernel + $initrd`
echo "kernel $kernel + initrd $initrd = $total bytes, budget $3"
test $total -le $3

#!/bin/bash
echo 128 > /sys/block/sdc/queue/max_sectors_kb
echo 1 > /sys/block/sdc/device/queue_depth

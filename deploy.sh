#!/bin/bash


docker build . -t ghcr.io/dryamvlad/jgf-scanner:main --platform linux/amd64 && \
echo $CR_PAT | docker login ghcr.io -u dryamvlad --password-stdin && \
docker push ghcr.io/dryamvlad/jgf-scanner:main && \
ssh root@142.93.117.43 'cd /root/wonnie/wwb && sh deploy.sh'
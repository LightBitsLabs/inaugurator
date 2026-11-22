FROM fedora:28
MAINTAINER ops@lightbitslabs.com

# Install other tools
RUN echo "fastmirror=True" >> /etc/dnf/dnf.conf

RUN dnf update -y

RUN dnf install -y \
    sudo \
    boost-devel \
    boost-static \
    openssl-devel \
    gcc-c++ \
    hwdata \
    kexec-tools \
    net-tools \
    parted \
    e2fsprogs \
    dosfstools \
    lvm2 \
    python-pip \
    make \
    kernel \
    lshw \
    pciutils \
    rsync \
    fio \
    ndctl \
    numactl \
    busybox \
    grubby && \
    dnf -y clean all

# Fedora 28 ends at kernel 5.0, which has no driver for NICs newer than 2019.
# The initrd takes its kernel, modules and firmware from a later Fedora instead.
# The packages go in with --noscripts: their scriptlets build a boot entry the
# container has no use for.
# The base image has no key for a later Fedora, so each package is checked against its
# sha256 here; a change of version needs the digests of the new packages.
ARG KERNEL_VERSION=5.11.22-100.fc32.x86_64
ARG FIRMWARE_VERSION=20210511-120.fc32
ARG KERNEL_REPO=https://archives.fedoraproject.org/pub/archive/fedora/linux/updates/32/Everything/x86_64/Packages
ARG KERNEL_CORE_SHA256=1329e02a1b0cf37041fe3286d609a1ffe31c60a5342658e46cba6430c9df4a69
ARG KERNEL_MODULES_SHA256=66eaa2e6a57df55abe7ac9ba88a71fcffa10901f1ff938d74c4a2e3bf4459e4c
ARG FIRMWARE_SHA256=25db0452e31be620cac669306b44c82725caf4af7635fa4df3d24e1a8a024a1f
RUN mkdir /tmp/kernel-packages && cd /tmp/kernel-packages && \
    curl --fail --silent --show-error --location --remote-name-all \
        ${KERNEL_REPO}/k/kernel-core-${KERNEL_VERSION}.rpm \
        ${KERNEL_REPO}/k/kernel-modules-${KERNEL_VERSION}.rpm \
        ${KERNEL_REPO}/l/linux-firmware-${FIRMWARE_VERSION}.noarch.rpm && \
    echo "${KERNEL_CORE_SHA256}  kernel-core-${KERNEL_VERSION}.rpm" > sha256 && \
    echo "${KERNEL_MODULES_SHA256}  kernel-modules-${KERNEL_VERSION}.rpm" >> sha256 && \
    echo "${FIRMWARE_SHA256}  linux-firmware-${FIRMWARE_VERSION}.noarch.rpm" >> sha256 && \
    sha256sum --check sha256 && \
    rpm -e --nodeps linux-firmware && \
    rpm -i --nodeps --noscripts *.rpm && \
    cd / && rm -fr /tmp/kernel-packages && \
    depmod ${KERNEL_VERSION}
ENV KERNEL_VERSION ${KERNEL_VERSION}

RUN pip install urllib3 requests pep8 pika==0.13.0 ipaddress mock==3.0.5 simplejson

# Edit sudoers file to avoid error: sudo: sorry, you must have a tty to run sudo
RUN sed -i -e "s/Defaults    requiretty.*/ #Defaults    requiretty/g" /etc/sudoers

WORKDIR /root

CMD make -C osmosis build -j 10 && \
    make -C osmosis egg

RUN rpm -i http://lbmirror/infra/inaugurator/nvme-cli-1.10.1-1.fc32.x86_64.rpm

WORKDIR /root/inaugurator
ENV BUILD_HOST local
ENTRYPOINT ["make"]
CMD ["nothing"]

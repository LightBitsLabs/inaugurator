FROM fedora:27
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
    grub2-efi-x64 \
    grub2-tools \
    grub2-tools-efi \
    grub2-tools-extra \
    grub2-common \
    grub2-pc \
    grub2-pc-modules \
    grub2-efi-x64-modules \
    grub2-efi-x64-cdboot \
    efibootmgr \
    busybox && \
    dnf -y clean all

RUN pip install urllib3 requests pep8 pika>=0.10.0

# Edit sudoers file to avoid error: sudo: sorry, you must have a tty to run sudo
RUN sed -i -e "s/Defaults    requiretty.*/ #Defaults    requiretty/g" /etc/sudoers

WORKDIR /root

CMD make -C osmosis build -j 10 && \
    make -C osmosis egg

RUN rpm -i https://rpmfind.net/linux/fedora/linux/releases/29/Everything/x86_64/os/Packages/n/nvme-cli-1.6-1.fc29.x86_64.rpm

WORKDIR /root/inaugurator
ENV BUILD_HOST local
ENTRYPOINT ["make"]
CMD ["nothing"]

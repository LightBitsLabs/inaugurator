##Current version
    2.8.43

##Compile driver for inaugurator
###step 1:
create a vm on virtual box with fedora 27

###step 2:
    wget the relevant driver on the vm
    tar the tar.gz driver file
    cd <driver folder>/src

###step 3:
    sudo make install

###step 4:
    modinfo i40e
    cd <driver path>
    xz the ko file created in modinfo path

###step 5:
    copy the ko.xz file from the vm to this folder by scp to shared server (lbmirror)

###step 6:
on Makefile.build:
    
    cp compiled_drivers/i40e.ko.xz /lib/modules/4.18.19-100.fc27.x86_64/kernel/drivers/net/ethernet/intel/i40e/i40e.ko.xz

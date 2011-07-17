'''
Created on Dec 6, 2010

@author: borja
'''
from demogrid.common.utils import create_ec2_connection, SSH
from demogrid.common import log
import time


class EC2ChefVolumeCreator(object):
    def __init__(self, demogrid_dir, ami, keypair, keyfile):
        self.demogrid_dir = demogrid_dir
        self.ami = ami
        self.keypair = keypair
        self.keyfile = keyfile

    def run(self):
        conn = create_ec2_connection()
        
        print "Creating instance"
		
        reservation = conn.run_instances(self.ami, 
                                         min_count=1, max_count=1,
                                         instance_type='t1.micro', 
                                         key_name=self.keypair)
        instance = reservation.instances[0]
        print "Instance %s created. Waiting for it to start..." % instance.id
        
        while instance.update() != "running":
            time.sleep(2)
        
        print "Instance running. Creating volume."
        
        vol = conn.create_volume(1, instance.placement)
        vol.attach(instance.id, '/dev/sdh')
        while vol.update() != "in-use":
            time.sleep(2)
        
        print "Volume created."

        ssh = SSH("ubuntu", instance.public_dns_name, self.keyfile)
        ssh.open()
        
        print "Preparing volume."
        ssh.scp("%s/lib/scripts/prepare_chef_volume.sh" % self.demogrid_dir,
                "/tmp/prepare_chef_volume.sh")
        
        ssh.run("chmod u+x /tmp/prepare_chef_volume.sh")

        ssh.run("sudo /tmp/prepare_chef_volume.sh")
        
        print "Copying Chef files."
        ssh.scp_dir("%s/chef" % self.demogrid_dir, "/chef")
                
        ssh.run("sudo umount /chef")
        
        print "Detaching volume"
        vol.detach()
        while vol.update() != "available":
            time.sleep(1)

        print "Creating snapshot"
        snap = vol.create_snapshot("DemoGrid Chef partition 0.2")
        snap.share(groups=['all'])
        
        vol.delete()
        
        print "The snapshot ID is %s" % snap.id

        print "Terminating instance"
        conn.terminate_instances([instance.id])
        while instance.update() != "terminated":
            time.sleep(2)
        print "Instance terminated"        
        



class EC2AMICreator(object):
    def __init__(self, demogrid_dir, base_ami, ami_name, snapshot, config):
        self.demogrid_dir = demogrid_dir
        self.base_ami = base_ami
        self.ami_name = ami_name
        self.snapshot = snapshot
        self.config = config

        self.keypair = config.get_keypair()
        self.keyfile = config.get_keyfile()
        if config.has_ec2_hostname():
            self.hostname = config.get_ec2_hostname()
            self.path = config.get_ec2_path()
            self.port = config.get_ec2_port()
        else:
            self.hostname = None
            self.path = None
            self.port = None
        self.username = config.get_ec2_username()
        self.scratch_dir = config.get_scratch_dir()

    def run(self):
        log.init_logging(2)

        conn = create_ec2_connection(hostname=self.hostname, path=self.path, port=self.port)

        print "Creating instance"
        reservation = conn.run_instances(self.base_ami, 
                                         min_count=1, max_count=1,
                                         instance_type='m1.small', 
                                         key_name=self.keypair)
        instance = reservation.instances[0]
        print "Instance %s created. Waiting for it to start..." % instance.id
        
        while instance.update() != "running":
            time.sleep(2)
        
        print "Instance running"
        print self.username, instance.public_dns_name, self.keyfile
        ssh = SSH(self.username, instance.public_dns_name, self.keyfile)
        try:
            ssh.open()
        except Exception, e:
            print e.message
            exit(1)
        
        if self.snapshot != None:
            print "Creating volume + attaching."
            
            vol = conn.create_volume(1, instance.placement, self.snapshot)
            vol.attach(instance.id, '/dev/sdh')
            while vol.update() != "in-use":
                time.sleep(2)
            
            print "Volume created."        
    
            print "Mounting volume."  
            ssh.run("sudo mkdir /chef")
            ssh.run("sudo mount -t ext3 /dev/sdh /chef")
            ssh.run("sudo chown -R %s /chef" % self.username)
        else:
            print "Copying Chef files"
            ssh.run("sudo mkdir /chef")
            ssh.run("sudo chown -R %s /chef" % self.username)
            ssh.scp_dir("%s/chef" % self.demogrid_dir, "/chef")
        
        # Some VMs don't include their hostname
        ssh.run("echo \"%s `hostname`\" | sudo tee -a /etc/hosts" % instance.private_ip_address)

        ssh.run("sudo apt-get install lsb-release")
        ssh.run("echo \"deb http://apt.opscode.com/ `lsb_release -cs` main\" | sudo tee /etc/apt/sources.list.d/opscode.list")
        ssh.run("wget -qO - http://apt.opscode.com/packages@opscode.com.gpg.key | sudo apt-key add -")
        ssh.run("sudo apt-get update")
        ssh.run("echo 'chef chef/chef_server_url string http://127.0.0.1:4000' | sudo debconf-set-selections")
        ssh.run("sudo apt-get -q=2 install chef")
        
        ssh.scp("%s/lib/ec2/chef.conf" % self.demogrid_dir,
                "/tmp/chef.conf")        
        
        ssh.run("echo '{ \"run_list\": \"recipe[demogrid::ec2]\", \"scratch_dir\": \"%s\" }' > /tmp/chef.json" % self.scratch_dir)

        ssh.run("sudo chef-solo -c /tmp/chef.conf -j /tmp/chef.json")    
        
        ssh.run("sudo update-rc.d -f nis remove")
        ssh.run("sudo update-rc.d -f chef-client remove")
        
        print "Removing private data and authorized keys"
        ssh.run("sudo find /root/.*history /home/*/.*history -exec rm -f {} \;", exception_on_error = False)
        ssh.run("sudo find / -name authorized_keys -exec rm -f {} \;")        
        
        if self.snapshot != None:
            ssh.run("sudo umount /chef")
            print "Detaching volume"
            vol.detach()
            while vol.update() != "available":
                time.sleep(1)        
            
        # Apparently instance.stop() will terminate
        # the instance (this is a known bug), so we 
        # use stop_instances instead.
        print "Stopping instance"
        conn.stop_instances([instance.id])
        while instance.update() != "stopped":
            time.sleep(2)
        print "Instance stopped"
        
        print "Creating AMI"
        # Doesn't actually return AMI. Have to make it public manually.
        ami = conn.create_image(instance.id, self.ami_name, description=self.ami_name)       
        
        print "Cleaning up"

        
        print "Terminating instance"
        #conn.terminate_instances([instance.id])
        #while instance.update() != "terminated":
        #    time.sleep(2)
        print "Instance terminated"   
                
        if self.snapshot != None:                
            vol.delete()     
        

class EC2AMIUpdater(object):
    def __init__(self, demogrid_dir, base_ami, ami_name, files, config):
        self.demogrid_dir = demogrid_dir
        self.base_ami = base_ami
        self.ami_name = ami_name
        self.files = files
        
        self.config = config

        self.keypair = config.get_keypair()
        self.keyfile = config.get_keyfile()
        if config.has_ec2_hostname():
            self.hostname = config.get_ec2_hostname()
            self.path = config.get_ec2_path()
            self.port = config.get_ec2_port()
        else:
            self.hostname = None
            self.path = None
            self.port = None
        self.username = config.get_ec2_username()

    def run(self):
        log.init_logging(2)
        
        conn = create_ec2_connection(hostname=self.hostname, path=self.path, port=self.port)

        print "Creating instance"
        reservation = conn.run_instances(self.base_ami, 
                                         min_count=1, max_count=1,
                                         instance_type='m1.small', 
                                         key_name=self.keypair)
        instance = reservation.instances[0]
        print "Instance %s created. Waiting for it to start..." % instance.id
        
        while instance.update() != "running":
            time.sleep(2)
        
        print "Instance running."

        print "Opening SSH connection."
        ssh = SSH(self.username, instance.public_dns_name, self.keyfile)
        ssh.open()
        
        print "Copying files"        
        for src, dst in self.files:
            ssh.scp(src, dst)
                  
        print "Removing private data and authorized keys"
        ssh.run("sudo find /root/.*history /home/*/.*history -exec rm -f {} \;")
        ssh.run("sudo find / -name authorized_keys -exec rm -f {} \;")
                  
        # Apparently instance.stop() will terminate
        # the instance (this is a known bug), so we 
        # use stop_instances instead.
        print "Stopping instance"
        conn.stop_instances([instance.id])
        while instance.update() != "stopped":
            time.sleep(2)
        print "Instance stopped"
        
        print "Creating AMI"
        
        # Doesn't actually return AMI. Have to make it public manually.
        ami = conn.create_image(instance.id, self.ami_name, description=self.ami_name)       
        
        if ami != None:
            print ami
        print "Cleaning up"

        
        print "Terminating instance"
        conn.terminate_instances([instance.id])
        while instance.update() != "terminated":
            time.sleep(2)
        print "Instance terminated"   

                
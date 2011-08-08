from cPickle import load
from boto.exception import BotoClientError, EC2ResponseError
from demogrid.common.utils import create_ec2_connection, SSH, MultiThread,\
    DemoGridThread, SSHCommandFailureException, SIGINTWatcher
import random
import time
import sys
import traceback
from demogrid.common import log
from demogrid.common.certs import CertificateGenerator
from demogrid.core.deploy import BaseDeployer, VM, ConfigureThread
from demogrid.core.topology import DeployData, EC2DeployData

class EC2VM(VM):
    def __init__(self, ec2_instance):
        self.ec2_instance = ec2_instance
        
    def __str__(self):
        return self.ec2_instance.id

class Deployer(BaseDeployer):
  
    def __init__(self, *args, **kwargs):
        BaseDeployer.__init__(self, *args, **kwargs)
        self.conn = None
        self.instances = None
        self.vols = []
        self.supports_create_tags = True

    def set_instance(self, inst):
        self.instance = inst
        self.__connect()         
    
    def __connect(self):
        config = self.instance.config
        keypair = config.get("ec2-keypair")
        zone = config.get("ec2-availability-zone")
        
        try:
            log.debug("Connecting to EC2...")
            ec2_server_hostname = config.get("ec2-server-hostname")
            ec2_server_port = config.get("ec2-server-port")
            ec2_server_path = config.get("ec2-server-path")
            
            if ec2_server_hostname != None:
                self.conn = create_ec2_connection(ec2_server_hostname,
                                                  ec2_server_port,
                                                  ec2_server_path) 
            else:
                self.conn = create_ec2_connection()
            
            if self.conn == None:
                print "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables are not set."
                exit(1)
            log.debug("Connected to EC2.")
        except BotoClientError, exc:
            print "\033[1;31mERROR\033[0m - Could not connect to EC2."
            print "        Reason: %s" % exc.reason
            exit(1)
        except Exception, exc:
            self.handle_unexpected_exception(exc)    
        
    def allocate_vm(self, node):
        topology = self.instance.topology
        
        instance_type = topology.get_deploy_data(node, "ec2", "instance_type")
        ami = topology.get_deploy_data(node, "ec2", "ami")

        image = self.conn.get_image(ami)
        if image == None:
            # Workaround for this bug:
            # https://bugs.launchpad.net/eucalyptus/+bug/495670
            image = [i for i in self.conn.get_all_images() if i.id == ami][0]
        
        log.info(" |- Launching a %s instance for %s." % (instance_type, node.id))
        reservation = image.run(min_count=1, 
                                max_count=1,
                                instance_type=instance_type,
                                security_groups= ["default"],
                                key_name=self.instance.config.get("ec2-keypair"),
                                placement = None)
        instance = reservation.instances[0]
        
        return EC2VM(instance)

    def resume_vm(self, node):
        ec2_instance_id = node.deploy_data.ec2.instance_id

        log.info(" |- Resuming instance %s for %s." % (ec2_instance_id, node.id))
        started = self.conn.start_instances([ec2_instance_id])            
        log.info(" |- Resumed instance %s." % ",".join([i.id for i in started]))
        
        return EC2VM(started[0])

    def post_allocate(self, domain, node, vm):
        ec2_instance = vm.ec2_instance
        
        if ec2_instance.private_ip_address != None:
            # A correct EC2 system should return this
            node.ip = ec2_instance.private_ip_address
        else:
            # Unfortunately, some EC2-ish systems won't return the private IP address
            # We fall back on the private_dns_name, which should still work
            # (plus, some EC2-ish systems actually set this to the IP address)
            node.ip = ec2_instance.private_dns_name

        node.hostname = ec2_instance.public_dns_name
        
        # TODO: The following won't work on EC2-ish systems behind a firewall.
        node.public_ip = ".".join(ec2_instance.public_dns_name.split(".")[0].split("-")[1:])

        if not node.has_property("deploy_data"):
            node.deploy_data = DeployData()
            node.deploy_data.ec2 = EC2DeployData()            

        node.deploy_data.ec2.instance_id = ec2_instance.id

        try:
            if self.supports_create_tags:
                self.conn.create_tags([ec2_instance.id], {"Name": "%s_%s" % (self.instance.id, node.id)})
        except:
            # Some EC2-ish systems don't support the create_tags call.
            # If it fails, we just silently ignore it, as it is not essential,
            # but make sure not to call it again, as EC2-ish systems will
            # timeout instead of immediately returning an error
            self.supports_create_tags = False


    def get_node_vm(self, nodes):
        ec2_instance_ids = [n.deploy_data.ec2.instance_id for d, n in nodes]
        reservations = self.conn.get_all_instances(ec2_instance_ids)
        node_vm = {}
        for r in reservations:
            instance = r.instances[0]
            node = [n for n in nodes if n.deploy_data.ec2.instance_id==instance.id][0]
            node_vm[node] = EC2VM(instance)
        return node_vm

    def stop_vms(self, nodes):
        ec2_instance_ids = [n.deploy_data.ec2.instance_id for d, n in nodes]
        log.info("Stopping EC2 instances %s." % ", ".join(ec2_instance_ids))
        stopped = self.conn.stop_instances(ec2_instance_ids)
        log.info("Stopped EC2 instances %s." % ", ".join([i.id for i in stopped]))

    def terminate_vms(self, nodes):
        ec2_instance_ids = [n.deploy_data.ec2.instance_id for d, n in nodes]
        log.info("Terminating EC2 instances %s." % ", ".join(ec2_instance_ids))
        terminated = self.conn.terminate_instances(ec2_instance_ids)
        log.info("Terminated EC2 instances %s." % ", ".join([i.id for i in terminated]))
        
    def wait_state(self, obj, state, interval = 2.0):
        jitter = random.uniform(0.0, 0.5)
        while True:
            time.sleep(interval + jitter)
            newstate = obj.update()
            if newstate == state:
                return True
        # TODO: Check errors    
        

    def cleanup(self):
        if self.no_cleanup:
            print "--no-cleanup has been specified, so DemoGrid will not release EC2 resources."
            print "Remember to do this manually"
        else:
            print "DemoGrid is attempting to release all EC2 resources..."
            try:
                if self.conn != None:
                    for v in self.vols:
                        if v.attachment_state == "attached":
                            v.detach()
                    if self.instances != None:
                        self.conn.terminate_instances([i.id for i in self.instances])
                    for v in self.vols:
                        self.wait_state(v, "available")        
                        v.delete()
                    print "DemoGrid has released all EC2 resources."
            except:
                traceback.print_exc()
                print "DemoGrid was unable to release all EC2 resources."
                if self.instances != None:
                    print "Please make sure the following instances have been terminated: " % [i.id for i in self.instances]
                if len(self.vols) > 0:
                    print "Please make sure the following volumes have been deleted: " % [v.id for v in self.vols]
        
            
    class NodeWaitThread(DemoGridThread):
        def __init__(self, multi, name, node, vm, deployer, depends = None):
            DemoGridThread.__init__(self, multi, name, depends)
            self.ec2_instance = vm.ec2_instance
            self.deployer = deployer
                        
        def run2(self):
            self.deployer.wait_state(self.ec2_instance, "running")
            log.info("Instance %s is running. Hostname: %s" % (self.ec2_instance.id, self.ec2_instance.public_dns_name))
            
    class NodeConfigureThread(ConfigureThread):
        def __init__(self, multi, name, domain, node, vm, deployer, depends = None, basic = True, chef = True):
            ConfigureThread.__init__(self, multi, name, domain, node, vm, deployer, depends, basic, chef)
            self.ec2_instance = self.vm.ec2_instance
            
        def connect(self):
            return self.ssh_connect(self.config.get("ec2-username"), self.ec2_instance.public_dns_name, self.config.get("ec2-keyfile"))
        
        def pre_configure(self, ssh):
            node = self.node
            instance = self.ec2_instance
            
            log.info("Setting up instance %s. Hostname: %s" % (instance.id, instance.public_dns_name), node)
                
        def post_configure(self, ssh):
            pass
            
# -------------------------------------------------------------------------- #
# Copyright 2010, University of Chicago                                      #
#                                                                            #
# Licensed under the Apache License, Version 2.0 (the "License"); you may    #
# not use this file except in compliance with the License. You may obtain    #
# a copy of the License at                                                   #
#                                                                            #
# http://www.apache.org/licenses/LICENSE-2.0                                 #
#                                                                            #
# Unless required by applicable law or agreed to in writing, software        #
# distributed under the License is distributed on an "AS IS" BASIS,          #
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.   #
# See the License for the specific language governing permissions and        #
# limitations under the License.                                             #
# -------------------------------------------------------------------------- #

##~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
##
## RECIPE: SimpleCA
##
## This recipe install a CA certificate and key so the node can use SimpleCA
## commands to sign certificate requests.
##
## Note that, instead of using GPT, we set up all the necessary files manually.
## This is necessary since the CA certificate is created beforehand by
## Globus Provision, instead of through the usual Globus installation procedure.
##
##~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

if ! File.exists?(node[:globus][:simpleCA] )

	# Create the basic directory structure

	directory node[:globus][:simpleCA] do
	  owner "root"
	  group "root"
	  mode "0755"
	  action :create
	  recursive true
	end

	directory "#{node[:globus][:simpleCA]}/certs" do
	  owner "root"
	  group "root"
	  mode "0755"
	  action :create
	end

	directory "#{node[:globus][:simpleCA]}/crl" do
	  owner "root"
	  group "root"
	  mode "0755"
	  action :create
	end

	directory "#{node[:globus][:simpleCA]}/newcerts" do
	  owner "root"
	  group "root"
	  mode "0755"
	  action :create
	end

	directory "#{node[:globus][:simpleCA]}/private" do
	  owner "root"
	  group "root"
	  mode "0700"
	  action :create
	end


	# Copy the CA certificate and key.
	cookbook_file "#{node[:globus][:simpleCA]}/cacert.pem" do
	  source "7d4be459.0"
	  mode 0644
	  owner "root"
	  group "root"
	end

	cookbook_file "#{node[:globus][:simpleCA]}/private/cakey.pem" do
	  source "ca_key.pem"
	  mode 0400
	  owner "root"
	  group "root"
	end


	# Various configuration files needed in the CA directory
	cookbook_file "#{node[:globus][:simpleCA]}/grid-ca-ssl.conf" do
	  source "grid-ca-ssl.conf"
	  mode 0644
	  owner "root"
	  group "root"
	end

	file "#{node[:globus][:simpleCA]}/index.txt" do
	  owner "root"
	  group "root"
	  mode "0644"
	  action :create
	end

	file "#{node[:globus][:simpleCA]}/serial" do
	  owner "root"
	  group "root"
	  mode "0644"
	  action :create
	  content "01\n"
	end

end




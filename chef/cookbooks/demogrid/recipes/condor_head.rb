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

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#
# RECIPE: Condor head node
#
# Set up a Condor head node.
#
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

class Chef::Recipe
  include MiscHelper
end


# The "condor" recipe handles actions that are common to
# both head and worker nodes.
include_recipe "demogrid::condor"

# The lrm_head attribute is part of the generated topology.rb file,
# and contains the FQDN of the head node.
server = node[:lrm_head]

# Domain (used by Condor for authorization). 
# This should eventually be included in the topology.
domain = server[server.index(".")+1, server.length]

# Run the Condor configuration script.
execute "condor_configure" do
  user "root"
  group "root"
  cwd node[:condor][:dir]
  command "./condor_configure --install=#{node[:condor][:dir]} --install-dir=#{node[:condor][:dir]} --local-dir=/var/condor --type=manager,submit"
  action :run
end

# Link to the global configuration file
link "/var/condor/condor_config" do
  to "#{node[:condor][:dir]}/etc/condor_config"
end

# Create the local configuration file.
template "/var/condor/condor_config.local" do
  source "condor_config.erb"
  mode 0644
  owner "condor"
  group "condor"
  variables(
    :server => server,
    :domain => domain,    
    :daemons => "COLLECTOR, MASTER, NEGOTIATOR, SCHEDD"
  )
end

# Restart Condor
execute "condor_stop" do
 user "root"
 group "root"
 command "/etc/init.d/condor stop"
 action :run
end

execute "condor_start" do
 user "root"
 group "root"
 command "/etc/init.d/condor start"
 action :run
end




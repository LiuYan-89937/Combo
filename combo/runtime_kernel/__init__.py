"""Fixed execution kernel for dynamic runtime instances.

Runtime components are imported from their defining submodules so importing one
kernel module never initializes the complete execution graph.
"""

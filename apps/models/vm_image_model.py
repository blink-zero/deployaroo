from apps import db

class VmImageModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_template_name = db.Column(db.String(100), nullable=False)
    image_human_name = db.Column(db.String(100), nullable=False)
    image_folder_name = db.Column(db.String(100), nullable=False)
    image_type = db.Column(db.String(50), nullable=False)
    ansible_match_name = db.Column(db.String(100), nullable=False)
    vmware_os_type = db.Column(db.String(100), nullable=False)
    image_icon_name = db.Column(db.String(100), nullable=False)
    network_type = db.Column(db.String(50), nullable=False)

    def __repr__(self):
        return f"<VmImageModel {self.image_human_name}>"

    def set_image_template_name(self, image_template_name):
        self.image_template_name = image_template_name

    def set_image_human_name(self, image_human_name):
        self.image_human_name = image_human_name

    def set_image_folder_name(self, image_folder_name):
        self.image_folder_name = image_folder_name

    def set_image_type(self, image_type):
        self.image_type = image_type

    def set_ansible_match_name(self, ansible_match_name):
        self.ansible_match_name = ansible_match_name

    def set_vmware_os_type(self, vmware_os_type):
        self.vmware_os_type = vmware_os_type

    def set_image_icon_name(self, image_icon_name):
        self.image_icon_name = image_icon_name

    def set_network_type(self, network_type):
        self.network_type = network_type

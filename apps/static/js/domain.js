document.addEventListener("DOMContentLoaded", function () {
    const modeSwitch = document.getElementById('modeSwitch');
    const createVmButton = document.getElementById('createVmButton');
    const stagedVmsPanel = document.getElementById('stagedVmsPanel');
    const stagedVmsList = document.getElementById('stagedVmsList');
    const togglePanelButton = document.getElementById('togglePanelButton');
    const stagedVmsBtn = document.getElementById('stagedVmsBtn');
    const bodyContent = document.querySelector('.content');
    const documentationBtn = document.querySelector('.documentation-btn');

    let stagedVms = [];
    let panelCollapsed = true;

    // Initialize UI
    initializeUI();

    // Event Listeners
    modeSwitch.addEventListener('change', handleModeSwitch);
    createVmButton.addEventListener('click', handleCreateVmButton);
    documentationBtn.addEventListener('click', showDocumentation);
    togglePanelButton.addEventListener('click', togglePanel);
    stagedVmsBtn.addEventListener('click', togglePanel);
    document.getElementById('deployVmsButton').addEventListener('click', deployVms);
    document.getElementById('confirmDeleteBtn').addEventListener('click', deleteItem);

    // Initialize settings modal
    initializeSettingsModal();

    function initializeUI() {
        modeSwitch.checked = true;
        createVmButton.innerHTML = '<i class="fas fa-plus"></i> Create VM';
        document.querySelector('.form-check-label').textContent = 'Single Mode';
        stagedVmsPanel.classList.remove('active');
        togglePanelButton.classList.add('d-none');
        bodyContent.classList.remove('panel-open');
    }

    function handleModeSwitch() {
        if (this.checked) {
            setSingleMode();
        } else {
            setMultiMode();
        }
    }

    function showDocumentation() {
        window.open('https://deployaroo.io/', '_blank');
    }

    function setSingleMode() {
        createVmButton.innerHTML = '<i class="fas fa-plus"></i> Create VM';
        document.querySelector('.form-check-label').textContent = 'Single Mode';
        stagedVmsPanel.classList.remove('active');
        togglePanelButton.classList.add('d-none');
        bodyContent.classList.remove('panel-open');
        enableAllImages();
    }

    function setMultiMode() {
        createVmButton.innerHTML = '<i class="fas fa-plus"></i> Stage VM';
        document.querySelector('.form-check-label').textContent = 'Multiple Mode';
        togglePanelButton.classList.remove('d-none');
        if (!panelCollapsed) {
            stagedVmsPanel.classList.add('active');
            bodyContent.classList.add('panel-open');
        }
        updateToggleButtonIcon();
        disableDomainControllerImages();
    }

    function handleCreateVmButton(event) {
        const imagetypeSelect = document.getElementById('imagetype');
        const selectedImage = imagetypeSelect.value;
        const domainControllerImages = [
            'windows-server-2022-datacenter-dexp-v23.01|win_server2022dc_de_ad|windows9Server64Guest'
        ];

        if (domainControllerImages.includes(selectedImage)) {
            event.preventDefault();
            $('#domainNameModal').modal('show');
        } else if (!modeSwitch.checked) {
            event.preventDefault();
            stageVm();
        }
    }

    function togglePanel() {
        panelCollapsed = !panelCollapsed;
        stagedVmsPanel.classList.toggle('active');
        bodyContent.classList.toggle('panel-open');
        updateToggleButtonIcon();
    }

    function updateToggleButtonIcon() {
        togglePanelButton.innerHTML = panelCollapsed ? 
            '<i class="fas fa-chevron-left"></i>' : 
            '<i class="fas fa-chevron-right"></i>';
    }

    function stageVm() {
        const hostname = document.getElementById('hostname').value;
        const ipaddress = document.getElementById('ipaddress').value;
        const [imagetype, machinetype, group, humanname, imageiconname] = document.getElementById('imagetype').value.split('|');
        const cpu = document.getElementById('cpu').value;
        const ram = document.getElementById('ram').value;

        if (hostname && ipaddress && imagetype && machinetype && group && cpu && ram) {
            const vm = { hostname, ipaddress, imagetype, machinetype, group, humanname, imageiconname, cpu, ram };
            stagedVms.push(vm);
            updateStagedVmsList();
        }
    }

    function updateStagedVmsList() {
        stagedVmsList.innerHTML = '';
        stagedVms.forEach((vm, index) => {
            const card = document.createElement('div');
            card.className = 'card vmcard mb-2 bg-secondary text-white border-0 slide-in';
            card.style.animationDelay = `${index * 0.1}s`;
            card.innerHTML = `
                <div class="card-body d-flex align-items-center p-3">
                    <img src="/static/images/64x64/${vm.imageiconname}" alt="${vm.imagetype}" class="vm-image-icon me-3">
                    <div class="flex-grow-1">
                        <h5 class="card-title mb-1">${vm.hostname}</h5>
                        <p class="card-text mb-0"><small>${vm.ipaddress} | ${vm.cpu} CPU | ${vm.ram} MB RAM</small></p>
                    </div>
                </div>
            `;
            stagedVmsList.appendChild(card);
        });
    }

    function deployVms() {
        if (stagedVms.length > 0) {
            document.getElementById('client_machines_list').value = JSON.stringify(stagedVms);
            document.getElementById('client-testing-form').submit();
        }
    }

    function deleteItem() {
        var itemId = document.querySelector('input[name="item_id"]').value;
        fetch(`/delete_domain_item/${itemId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        })
        .then(response => {
            if (response.ok) {
                window.location.href = '/home';
            } else {
                alert('Failed to delete domain item.');
            }
        })
        .catch(error => console.error('Error:', error));
    }

    function initializeSettingsModal() {
        $('#settingsModal').on('show.bs.modal', function (event) {
            var modal = $(this);
            modal.find('#settings-content').html('<p>Loading settings...</p>');

            axios.get('/get_settings', {
                params: {
                    item_id: document.querySelector('input[name="item_id"]').value
                }
            })
            .then(response => {
                const settings = response.data;
                let settingsHtml = '<div class="table-responsive"><table class="table table-dark table-striped">';
                for (const [key, value] of Object.entries(settings)) {
                    settingsHtml += `<tr><th>${key}</th><td>${value}</td></tr>`;
                }
                settingsHtml += '</table></div>';
                modal.find('#settings-content').html(settingsHtml);
            })
            .catch(error => {
                modal.find('#settings-content').html('<p>Error loading settings.</p>');
                console.error('Error fetching settings:', error);
            });
        });
    }

    function disableDomainControllerImages() {
        const domainControllerOptions = [
            'windows-server-2022-datacenter-dexp-v23.01|win_server2022dc_de_ad|windows9Server64Guest'
        ];
        const imagetypeSelect = document.getElementById('imagetype');
        for (const option of imagetypeSelect.options) {
            if (domainControllerOptions.includes(option.value)) {
                option.disabled = true;
            }
        }
    }

    function enableAllImages() {
        const imagetypeSelect = document.getElementById('imagetype');
        for (const option of imagetypeSelect.options) {
            option.disabled = false;
        }
    }
});
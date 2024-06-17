$('#sidebarCollapse').on('click', function () {
    $('#sidebar').toggleClass('active');
    $('#body').toggleClass('active');
});

toastr.options = {
    "debug": false,
    "positionClass": "toast-bottom-right",
    "closeButton": true
}

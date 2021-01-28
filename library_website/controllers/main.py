from odoo import http
from odoo.http import request

class Main(http.Controller):
    @http.route('/checkouts', auth='user', website=True)
    def checkouts(self, **kwargs):
        Checkout = request.env['library.checkout']
        checkouts = Checkout.search([])
        return request.render(
            'library_website.index',
            {'docs': checkouts})
    
    @http.route('/checkout/<model("library.checkout"):doc>',
    auth="user", # default, but made explicit here
    website=True)
    def checkout(self, doc, **kwargs):
        return http.request.render(
            'library_website.checkout',
            {'doc': doc})

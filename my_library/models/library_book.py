from odoo import models, fields, api, exceptions
from odoo.addons import decimal_precision as dp
from odoo.exceptions import ValidationError
from datetime import timedelta
from odoo.exceptions import UserError
from odoo.tools.translate import _


class BaseArchive(models.AbstractModel):
    _name = 'base.archive'
    active = fields.Boolean(default=True)

    def do_archive(self):
        for record in self:
            record.active = not record.active


class LibraryBook(models.Model): 
    _name = 'library.book2'
    _description = 'Library Book'
    _order = 'date_release desc, name'
    _rec_name = 'short_name'
    _inherit = ['base.archive']
    short_name = fields.Char('Short Title', translate=True, index=True)
    notes = fields.Text('Internal Notes')
    state = fields.Selection([
                ('draft', 'Unavailable'),
                ('available', 'Available'),
                ('borrowed', 'Borrowed'),
                ('lost', 'Lost')],
                'State', default="draft")
    description = fields.Html('Description', sanitize=True, strip_style=False)
    cover = fields.Binary('Book Cover')
    out_of_print = fields.Boolean('Out of Print?') 
    name = fields.Char('Title', required=True)
    date_release = fields.Date('Release Date')
    author_ids = fields.Many2many('res.partner', string='Authors')
    date_updated = fields.Datetime('Last Updated')
    pages = fields.Integer('Number of Pages',
            groups='base.group_user',
            states={'lost': [('readonly', True)]},
            help='Total book page count', company_dependent=False
        )
    reader_rating = fields.Float(
        'Reader Average Rating',
        digits=(14, 4),  # Optional precision (total, decimals),
    )
    cost_price = fields.Float('Book Cost', dp.get_precision('Book Price'))
    currency_id = fields.Many2one('res.currency', string='Currency')
    retail_price = fields.Monetary('Retail Price',
                                    # optional: currency_field='currency_id',
                                  )
    publisher_id = fields.Many2one(
        'res.partner', string='Publisher',
        # optional:
        ondelete='set null',
        context={},
        domain=[],
    )
    category_id = fields.Many2one('library.book.category')
    age_days = fields.Float(
            string='Days Since Release',
            compute='_compute_age',
            inverse='_inverse_age',
            search='_search_age',
            store=False,
            # optional
            compute_sudo=False  # optional
    )
    publisher_city = fields.Char(
        'Publisher City',
        related='publisher_id.city',
        readonly=True)
    ref_doc_id = fields.Reference(
                    selection='_referencable_models',
                    string='Reference Document')
    manager_remarks = fields.Text('Manager Remarks')
    isbn = fields.Char('ISBN')
    old_edition = fields.Many2one('library.book', string='Old Edition')

    _sql_constraints = [
        ('name_uniq',
         'UNIQUE (name)',
         'Book title must be unique.'),
         ('positive_page',
          'CHECK(pages>0)',
          'No of pages must be positive')
        ]

    def name_get(self):
        result = []
        for book in self:
            authors = book.author_ids.mapped('name')
            name = '%s (%s)' % (book.name, ', '.join(authors))
            result.append((book.id, name))
            return result

    @api.constrains('date_release')
    def _check_release_date(self):
        for record in self:
            if record.date_release \
                and record.date_release > fields.Date.today():
                raise models.ValidationError(
                        'Release date must be in the past')

    @api.depends('date_release')
    def _compute_age(self):
        today = fields.Date.today()
        for book in self.filtered('date_release'):
            delta = today - book.date_release
            book.age_days = delta.days

    def _inverse_age(self):
        today = fields.Date.today()
        for book in self.filtered('date_release'):
            d = today - timedelta(days=book.age_days)
            book.date_release = d

    def _search_age(self, operator, value):
        today = fields.Date.today()
        value_days = timedelta(days=value)
        value_date = today - value_days
        # convert the operator:
        # book with age > value have a date < value_date
        operator_map = {
            '>': '<', '>=': '<=',
            '<': '>', '<=': '>=',
        }
        new_op = operator_map.get(operator, operator)
        return [('date_release', new_op, value_date)]

    @api.model
    def _referencable_models(self):
        models = self.env['ir.model'].search([
            ('field_id.name', '=', 'message_ids')])
        return [(x.model, x.name) for x in models]

    @api.model
    def is_allowed_transition(self, old_state, new_state):
        allowed = [('draft', 'available'),
                    ('available', 'borrowed'),
                    ('borrowed', 'available'),
                    ('available', 'lost'),
                    ('borrowed', 'lost'),
                    ('lost', 'available')]
        return (old_state, new_state) in allowed

    @api.multi
    def change_state(self, new_state):
        for book in self:
            if book.is_allowed_transition(book.state, new_state):
                book.state = new_state
            else:
                msg = _('Moving from %s to %s is not allowed') % \
                        (book.state, new_state)
                raise UserError(msg)

    @api.model
    def make_available(self):
        self.change_state('available')

    @api.model
    def make_borrowed(self):
        self.change_state('borrowed')

    @api.model
    def make_lost(self):
        self.change_state('lost')
 
    @api.model
    def get_all_library_members(self):
        library_member_model = self.env['library.member']
        return library_member_model.search([])
    
    @api.multi
    def change_update_date(self):
        self.ensure_one()
        self.ensure_one()
        self.update({
            'date_updated': fields.Datetime.now(),
        })

    def find_book(self):
        domain = [
            '|',
            '&', ('name', 'ilike', 'Book Name'),
            ('category_id.name', 'ilike', 'Category Name'),
            '&', ('name', 'ilike', 'Book Name 2'),
            ('category_id.name', 'ilike', 'Category Name 2')
        ]
        books = self.search(domain)

    @api.model
    def sort_books_by_date(self, books):
        return books.sorted(key='release_date')

    def make_borrowed(self):
        day_to_borrow = self.category_id.max_borrow_days or 10
        self.date_return = fields.Date.today() + \
            timedelta(days=day_to_borrow)
        return super(LibraryBook, self).make_borrowed()
    
    def make_available(self):
        self.date_return = False
        return super(LibraryBook, self).make_available()
    
    @api.model
    def create(self, values):
        if not self.user_has_groups('my_library.acl_book_librarian'):
            if 'manager_remarks' in values:
                raise UserError(
                    'You are not allowed to modify '
                    'manager_remarks'
                )
        return super(LibraryBook, self).create(values)

    @api.multi
    def write(self, values):
        if not self.user_has_groups('my_library.acl_book_librarian'):
            if 'manager_remarks' in values:
                raise UserError(
                    'You are not allowed to modify '
                    'manager_remarks'
                )
        return super(LibraryBook, self).write(values)
    
    @api.model
    def _name_search(self, name='', args=None, operator='ilike',
                     limit=100, name_get_uid=None):
        args = [] if args is None else args.copy()
        if not(name == '' and operator == 'ilike'):
            args += ['|', '|',
                ('name', operator, name),
                ('isbn', operator, name),
                ('author_ids.name', operator, name)
            ]
        return super(LibraryBook, self)._name_search(
            name=name, args=args, operator=operator,
            limit=limit, name_get_uid=name_get_uid)
    
    @api.model
    def _get_average_cost(self):
        grouped_result = self.read_group(
            [('cost_price', "!=", False)],  # Domain
            ['category_id', 'cost_price:avg'],  # Fields to access
            ['category_id']  # group_by
        )
        return grouped_result
    
    @api.model
    def _update_book_price(self):
        all_books = self.search([])
        for book in all_books:
            book.cost_price += 10
    
    @api.model
    def update_book_price(self, category, amount_to_increase):
        category_books = self.search([('category_id', '=', category.id)])
        for book in category_books:
            book.cost_price += amount_to_increase
    
    def book_rent(self):
        self.ensure_one()
        if self.state != 'available':
            raise UserError(_('Book is not available for \
                renting'))
    
    def average_book_occupation(self):
        sql_query = """
                    SELECT
                    lb.name,
                    avg((EXTRACT(epoch from age(return_date, rent_date)) /
                    86400))::int
                    FROM
                    library_book_rent AS lbr
                    JOIN
                    library_book as lb ON lb.id = lbr.book_id
                    WHERE lbr.state = 'returned'
                    GROUP BY lb.name;"""
        self.env.cr.execute(sql_query)
        result = self.env.cr.fetchall()
        # logger.info("Average book occupation: %s", result)


class ResPartner(models.Model):
    _inherit = 'res.partner'
    published_book_ids = fields.One2many(
        'library.book', 'publisher_id',
        string='Published Books')
    authored_book_ids = fields.Many2many(
        'library.book',
        string='Authored Books',  # relation='library_book_res_partner_rel'
    )
    count_books = fields.Integer('Number of Authored Books',
                                 compute='_compute_count_books')

    @api.depends('authored_book_ids')
    def _compute_count_books(self):
        for r in self:
            r.count_books = len(r.authored_book_ids)


class LibraryMember(models.Model):
    _name = 'library.member'
    _inherits = {'res.partner': 'partner_id'}
    partner_id = fields.Many2one(
        'res.partner',
        ondelete='cascade')
    date_start = fields.Date('Member Since')
    date_end = fields.Date('Termination Date')
    member_number = fields.Char()
    date_of_birth = fields.Date('Date of birth')


class LibraryBook(models.Model):
    _inherit = 'library.book'
    date_return = fields.Date('Date to return')
    

class LibraryBookRent(models.Model):
    _name = 'library.book.rent'
    book_id = fields.Many2one('library.book', 'Book', required=True)
    borrower_id = fields.Many2one('res.partner', 'Borrower',
    required=True)
    state = fields.Selection([('ongoing', 'Ongoing'), ('returned',
                             'Returned')],
                             'State', default='ongoing',
                             required=True)
    book_id = fields.Many2one('library.book', 'Book', required=True)
    rent_date = fields.Date(default=fields.Date.today)
    return_date = fields.Date()
    rent_as_superuser = self.env['library.book.rent'].sudo()
    state = fields.Selection([('ongoing', 'Ongoing'),
                              ('returned', 'Returned'), ('lost',
                              'Lost')],
                             'State', default='ongoing',
                             required=True)

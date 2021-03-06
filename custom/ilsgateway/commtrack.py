import logging
import traceback
from django.contrib.auth.models import User
from corehq.apps.locations.models import Location
from corehq.apps.sms.mixin import PhoneNumberInUseException, VerifiedNumber
from corehq.apps.users.models import WebUser, CommCareUser, CouchUser, UserRole
from custom.api.utils import apply_updates
from custom.ilsgateway.api import ILSGatewayEndpoint
from corehq.apps.commtrack.models import Product, LocationType, SupplyPointCase, CommTrackUser, CommtrackConfig, \
    CommtrackActionConfig
from dimagi.utils.dates import force_to_datetime
from custom.ilsgateway.models import MigrationCheckpoint
from requests.exceptions import ConnectionError
from datetime import datetime
from custom.ilsgateway.api import Location as Loc


def retry(retry_max):
    def wrap(f):
        def wrapped_f(*args, **kwargs):
            retry_count = 0
            fail = False
            result = None
            while retry_count < retry_max:
                try:
                    result = f(*args, **kwargs)
                    fail = False
                    break
                except Exception:
                    retry_count += 1
                    fail = True
                    logging.error('%d/%d tries failed' % (retry_count, retry_max))
                    logging.error(traceback.format_exc())
            if fail:
                logging.error(f.__name__ + ": number of tries exceeds limit")
                logging.error("args: %s, kwargs: %s" % (args, kwargs))
            return result
        return wrapped_f
    return wrap


@retry(5)
def sync_ilsgateway_product(domain, ilsgateway_product):
    product = Product.get_by_code(domain, ilsgateway_product.sms_code)
    product_dict = {
        'domain': domain,
        'name': ilsgateway_product.name,
        'code': ilsgateway_product.sms_code,
        'unit': str(ilsgateway_product.units),
        'description': ilsgateway_product.description,
    }
    if product is None:
        product = Product(**product_dict)
        product.save()
    else:
        if apply_updates(product, product_dict):
            product.save()
    return product


@retry(5)
def sync_ilsgateway_webuser(domain, ilsgateway_webuser):
    user = WebUser.get_by_username(ilsgateway_webuser.email.lower())
    user_dict = {
        'first_name': ilsgateway_webuser.first_name,
        'last_name': ilsgateway_webuser.last_name,
        'is_staff': ilsgateway_webuser.is_staff,
        'is_active': ilsgateway_webuser.is_active,
        'is_superuser': ilsgateway_webuser.is_superuser,
        'last_login': force_to_datetime(ilsgateway_webuser.last_login),
        'date_joined': force_to_datetime(ilsgateway_webuser.date_joined),
        'password_hashed': True,
    }
    sp = SupplyPointCase.view('hqcase/by_domain_external_id',
                              key=[domain, str(ilsgateway_webuser.location)],
                              reduce=False,
                              include_docs=True,
                              limit=1).first()
    role_id = ilsgateway_webuser.role_id if hasattr(ilsgateway_webuser, 'role_id') else None
    location_id = sp.location_id if sp else None

    if user is None:
        try:
            user = WebUser.create(domain=None, username=ilsgateway_webuser.email.lower(),
                                  password=ilsgateway_webuser.password, email=ilsgateway_webuser.email, **user_dict)
            user.add_domain_membership(domain, role_id=role_id, location_id=location_id)
            user.save()
        except Exception as e:
            logging.error(e)
    else:
        if domain not in user.get_domains():
            user.add_domain_membership(domain, role_id=role_id, location_id=location_id)
            user.save()

    return user


def add_location(user, location_id):
    commtrack_user = CommTrackUser.wrap(user.to_json())
    if location_id:
        loc = Location.get(location_id)
        commtrack_user.clear_locations()
        commtrack_user.add_location(loc, create_sp_if_missing=True)

@retry(5)
def sync_ilsgateway_smsuser(domain, ilsgateway_smsuser):
    username_part = "%s%d" % (ilsgateway_smsuser.name.strip().replace(' ', '.').lower(), ilsgateway_smsuser.id)
    username = "%s@%s.commcarehq.org" % (username_part, domain)
    user = CouchUser.get_by_username(username)
    splitted_value = ilsgateway_smsuser.name.split(' ', 1)
    first_name = last_name = ''
    if splitted_value:
        first_name = splitted_value[0][:30]
        last_name = splitted_value[1][:30] if len(splitted_value) > 1 else ''

    user_dict = {
        'first_name': first_name,
        'last_name': last_name,
        'is_active': bool(ilsgateway_smsuser.is_active),
        'email': ilsgateway_smsuser.email,
        'user_data': {
            "role": ilsgateway_smsuser.role
        }
    }

    if ilsgateway_smsuser.phone_numbers:
        user_dict['phone_numbers'] = [ilsgateway_smsuser.phone_numbers[0].replace('+', '')]
        user_dict['user_data']['backend'] = ilsgateway_smsuser.backend



    sp = SupplyPointCase.view('hqcase/by_domain_external_id',
                              key=[domain, str(ilsgateway_smsuser.supply_point)],
                              reduce=False,
                              include_docs=True,
                              limit=1).first()
    location_id = sp.location_id if sp else None

    if user is None and username_part:
        try:
            password = User.objects.make_random_password()
            user = CommCareUser.create(domain=domain, username=username, password=password,
                                       email=ilsgateway_smsuser.email, commit=False)
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = bool(ilsgateway_smsuser.is_active)
            user.user_data = user_dict["user_data"]
            if "phone_numbers" in user_dict:
                user.set_default_phone_number(user_dict["phone_numbers"][0])
                try:
                    user.save_verified_number(domain, user_dict["phone_numbers"][0], True, ilsgateway_smsuser.backend)
                except PhoneNumberInUseException as e:
                    v = VerifiedNumber.by_phone(user_dict["phone_numbers"][0], include_pending=True)
                    v.delete()
                    user.save_verified_number(domain, user_dict["phone_numbers"][0], True, ilsgateway_smsuser.backend)
            dm = user.get_domain_membership(domain)
            dm.location_id = location_id
            user.save()
            add_location(user, location_id)

        except Exception as e:
            logging.error(e)
    else:
        dm = user.get_domain_membership(domain)
        current_location_id = dm.location_id if dm else None
        save = False

        if current_location_id != location_id:
            dm.location_id = location_id
            add_location(user, location_id)
            save = True

        if apply_updates(user, user_dict) or save:
            user.save()
    return user


@retry(5)
def sync_ilsgateway_location(domain, endpoint, ilsgateway_location):
    location = Location.view('commtrack/locations_by_code',
                             key=[domain, ilsgateway_location.code.lower()],
                             include_docs=True).first()
    if not location:
        if ilsgateway_location.parent:
            loc_parent = SupplyPointCase.view('hqcase/by_domain_external_id',
                                              key=[domain, str(ilsgateway_location.parent)],
                                              reduce=False,
                                              include_docs=True).first()
            if not loc_parent:
                parent = endpoint.get_location(ilsgateway_location.parent)
                loc_parent = sync_ilsgateway_location(domain, endpoint, Loc.from_json(parent))
            else:
                loc_parent = loc_parent.location
            location = Location(parent=loc_parent)
        else:
            location = Location()
            location.lineage = []
        location.domain = domain
        location.name = ilsgateway_location.name
        location.metadata = {'groups': ilsgateway_location.groups}
        if ilsgateway_location.latitude:
            location.latitude = float(ilsgateway_location.latitude)
        if ilsgateway_location.longitude:
            location.longitude = float(ilsgateway_location.longitude)
        location.location_type = ilsgateway_location.type
        location.site_code = ilsgateway_location.code
        location.external_id = str(ilsgateway_location.id)
        location.save()
        if not SupplyPointCase.get_by_location(location):
            SupplyPointCase.create_from_location(domain, location)
    else:
        location_dict = {
            'name': ilsgateway_location.name,
            'latitude': float(ilsgateway_location.latitude) if ilsgateway_location.latitude else None,
            'longitude': float(ilsgateway_location.longitude) if ilsgateway_location.longitude else None,
            'type': ilsgateway_location.type,
            'site_code': ilsgateway_location.code.lower(),
            'external_id': str(ilsgateway_location.id),
        }
        case = SupplyPointCase.get_by_location(location)
        if apply_updates(location, location_dict):
            location.save()
            if case:
                case.update_from_location(location)
            else:
                SupplyPointCase.create_from_location(domain, location)
    return location


def products_sync(domain, endpoint, **kwargs):
    for product in endpoint.get_products(**kwargs):
        sync_ilsgateway_product(domain, product)


def webusers_sync(project, endpoint, **kwargs):
    for user in endpoint.get_webusers(**kwargs):
        if user.email:
            if not user.is_superuser:
                setattr(user, 'role_id', UserRole.get_read_only_role_by_domain(project).get_id)
            sync_ilsgateway_webuser(project, user)


def smsusers_sync(project, endpoint, **kwargs):
    has_next = True
    next_url = None
    while has_next:
        next_url_params = next_url.split('?')[1] if next_url else None
        meta, users = endpoint.get_smsusers(next_url_params=next_url_params, **kwargs)
        for user in users:
            sync_ilsgateway_smsuser(project, user)

        if not meta.get('next', False):
            has_next = False
        else:
            next_url = meta['next']


def locations_sync(project, endpoint, **kwargs):
    for location_type in ['facility', 'district', 'region']:
        has_next = True
        next_url = None
        while has_next:
            next_url_params = next_url.split('?')[1] if next_url else None
            meta, locations = endpoint.get_locations(type=location_type, next_url_params=next_url_params, **kwargs)
            for location in locations:
                sync_ilsgateway_location(project, endpoint, location)

            if not meta.get('next', False):
                has_next = False
            else:
                next_url = meta['next']


def commtrack_settings_sync(project):
    locations_types = ["MOHSW", "REGION", "DISTRICT", "FACILITY"]
    config = CommtrackConfig.for_domain(project)
    config.location_types = []
    for i, value in enumerate(locations_types):
        if not any(lt.name == value
                   for lt in config.location_types):
            allowed_parents = [locations_types[i - 1]] if i > 0 else [""]
            config.location_types.append(
                LocationType(name=value, allowed_parents=allowed_parents, administrative=(value != 'FACILITY')))
    actions = [action.keyword for action in config.actions]
    if 'delivered' not in actions:
        config.actions.append(
            CommtrackActionConfig(
                action='receipts',
                keyword='delivered',
                caption='Delivered')
        )
    config.save()


def bootstrap_domain(ilsgateway_config):
    domain = ilsgateway_config.domain
    start_date = datetime.today()
    endpoint = ILSGatewayEndpoint.from_config(ilsgateway_config)
    try:
        checkpoint = MigrationCheckpoint.objects.get(domain=domain)
        date = checkpoint.date
    except MigrationCheckpoint.DoesNotExist:
        checkpoint = MigrationCheckpoint()
        checkpoint.domain = domain
        date = None
        commtrack_settings_sync(domain)
    try:
        products_sync(domain, endpoint, date=date)
        locations_sync(domain, endpoint, date=date)
        webusers_sync(domain, endpoint, date=date)
        smsusers_sync(domain, endpoint, date=date)
        
        checkpoint.date = start_date
        checkpoint.save()
    except ConnectionError as e:
        logging.error(e)
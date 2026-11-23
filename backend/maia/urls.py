from django.contrib import admin
from django.urls import path

from api import capture, capture_mail, closings, easybroker, location
from api.auth import login_view, logout_view, session_view
from api.routes import api
from api.whatsapp import webhook

urlpatterns = [
    path("api/crm/easybroker/connections", easybroker.connection_list),
    path("api/crm/easybroker/connections/<uuid:connection_id>/actions", easybroker.connection_action),
    path("api/crm/easybroker/connections/<uuid:connection_id>/sync", easybroker.sync),
    path("api/crm/easybroker/runs/<uuid:run_id>", easybroker.run),
    path("api/crm/easybroker/imports", easybroker.import_list),
    path("api/crm/easybroker/imports/<uuid:listing_id>", easybroker.import_detail),
    path("api/crm/easybroker/imports/<uuid:listing_id>/actions", easybroker.import_action),
    path("api/crm/properties/<int:offer_id>/result", closings.property_result),
    path("api/crm/closings", closings.listing),
    path("api/crm/closings/identities", closings.identities),
    path("api/crm/closings/searches", closings.searches),
    path("api/crm/closings/offers/<int:offer_id>/proposal", closings.proposal),
    path("api/crm/closings/<uuid:closing_id>", closings.detail),
    path("api/crm/closings/<uuid:closing_id>/preview", closings.summary),
    path("api/crm/closings/<uuid:closing_id>/actions", closings.action),
    path("api/location/config", location.config),
    path("api/location/map-session", location.map_session),
    path("api/location/search", location.search),
    path("api/location/points/<uuid:point_id>", location.point),
    path("api/location/properties/<int:property_id>", location.property_location),
    path("api/capture/catalog", capture.options),
    path("api/capture/mail/webhook", capture_mail.webhook),
    path("api/capture/account", capture.account),
    path("api/capture/requests", capture.listing),
    path("api/capture/requests/<uuid:capture_id>", capture.detail),
    path("api/capture/requests/<uuid:capture_id>/contract", capture.contract_document),
    path("api/capture/requests/<uuid:capture_id>/upload", capture.upload),
    path("api/capture/assets/<uuid:asset_id>", capture.asset),
    path("api/crm/captures", capture.crm_list),
    path("api/crm/captures/<uuid:capture_id>", capture.crm_detail),
    path("api/whatsapp/webhook", webhook),
    path("admin/", admin.site.urls),
    path("api/session", session_view),
    path("api/auth/login", login_view),
    path("api/auth/logout", logout_view),
    path("api/", api.urls),
]

"""
URLs for the certificates app.
"""

from django.conf.urls import patterns, url
from django.conf import settings

from certificates import views

urlpatterns = patterns(
    '',

    # Certificates HTML view
    url(
        r'^user/(?P<user_id>[^/]*)/course/{course_id}'.format(course_id=settings.COURSE_ID_PATTERN),
        views.render_html_view,
        name='html_view'
    ),

    # End-points used by student support
    # The views in the lms/djangoapps/support use these end-points
    # to retrieve certificate information and regenerate certificates.
    url(r'search', views.search_by_user, name="search"),
    url(r'regenerate', views.regenerate_certificate_for_user, name="regenerate_certificate_for_user"),

# GET /view

# GET /view/<certificate_id>
# DELETE /view/<certificate_id>

# GET /course/<course_id>
# POST /course/<course_id>
# PUT /course/<course_id>
)


if settings.FEATURES.get("ENABLE_OPENBADGES", False):
    urlpatterns += (
        url(
            r'^badge_share_tracker/{}/(?P<network>[^/]+)/(?P<student_username>[^/]+)/$'.format(
                settings.COURSE_ID_PATTERN
            ),
            views.track_share_redirect,
            name='badge_share_tracker'
        ),
    )

if settings.FEATURES.get('ENABLE_PDF_CERTIFICATES'):
    urlpatterns += (
        url(
            r'^pdf/view/user/(?P<user_id>[^/]*)/course/{course_id}'.format(
                course_id=settings.COURSE_ID_PATTERN,
            ),
            views.redirect_pdf,
            name='pdf_view',
        ),
        url(
            r'^pdf/request/course/{course_id}'.format(
                course_id=settings.COURSE_ID_PATTERN,
            ),
            views.request_pdf,
            name='pdf_request',
        ),
    )

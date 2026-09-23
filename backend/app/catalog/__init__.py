"""Catalog services and providers.

The package deliberately exposes only :class:`CatalogService` to the rest of
the application.  The service owns mode selection; callers never need to
know whether a result came from the synthetic fixture or EKT.
"""

from app.catalog.service import CatalogService

__all__ = ["CatalogService"]

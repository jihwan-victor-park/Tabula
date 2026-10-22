"""Versioned product API. Mounted under /v1 by clawbot.api.app."""

from fastapi import APIRouter

from clawbot.api.v1 import (
    audit, auth, catalog, connectors, dev, store, fulfilment, imports, inventory, operations, purchasing, replenishment, suppliers,
    tenants,
)

router = APIRouter(prefix="/v1")
router.include_router(auth.router)
router.include_router(tenants.router)
router.include_router(catalog.router)
router.include_router(suppliers.router)
router.include_router(inventory.router)
router.include_router(imports.router)
router.include_router(replenishment.router)
router.include_router(connectors.router)
router.include_router(purchasing.router)
router.include_router(fulfilment.router)
router.include_router(operations.router)
router.include_router(store.router)
router.include_router(dev.router)
router.include_router(audit.router)

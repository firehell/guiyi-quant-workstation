"""Vendor readiness for the late-provider job's single authorized attempt."""


def provider_ready(updater, day):
    if updater.rqdata is None:
        updater.rqdata = updater.rqdata_factory()
    return updater.rqdata.is_future_data_ready(day)

# =============================================================================
# Minet Multithreaded Fetch
# =============================================================================
#
# Exposing a specialized quenouille wrapper grabbing various urls from the
# web in a multithreaded fashion.
#
import mimetypes
from collections import namedtuple
from quenouille import imap_unordered
from ural import get_domain_name, ensure_protocol

from minet.utils import (
    create_safe_pool,
    guess_response_encoding,
    request
)

from minet.defaults import (
    DEFAULT_GROUP_PARALLELISM,
    DEFAULT_GROUP_BUFFER_SIZE,
    DEFAULT_THROTTLE
)

# Mimetypes init
mimetypes.init()

worker_payload_fields = [
    'http',
    'item',
    'url',
    'request_args'
]

FetchWorkerPayload = namedtuple(
    'FetchWorkerPayload',
    worker_payload_fields,
    defaults=[None] * len(worker_payload_fields)
)

worker_result_fields = [
    'url',
    'item',
    'error',
    'response',
    'meta'
]

FetchWorkerResult = namedtuple(
    'FetchWorkerResult',
    worker_result_fields,
    defaults=[None] * len(worker_result_fields)
)


def fetch(iterator, key=None, request_args=None, threads=25,
          throttle=DEFAULT_THROTTLE, guess_extension=True,
          guess_encoding=True):
    """
    Function returning a multithreaded iterator over fetched urls.

    Args:
        iterator (iterable): An iterator over urls or arbitrary items.
        key (callable, optional): Function extracting url from yielded items.
        request_args (callable, optional): Function returning specific
            arguments to pass to the request for a yielded item.
        threads (int, optional): Number of threads to use. Defaults to 25.
        throttle (float, optional): Per-domain throttle in seconds.
            Defaults to 0.2.
        guess_extension (bool, optional): Attempt to guess the resource's
            extension? Defaults to True.
        guess_encoding (bool, optional): Attempt to guess the resource's
            encoding? Defaults to True.

    Yields:
        FetchWorkerResult

    """

    # Creating the http pool manager
    http = create_safe_pool(
        num_pools=threads * 2,
        maxsize=1
    )

    # Thread worker
    def worker(payload):
        http, item, url, request_args = payload

        if url is None:
            return FetchWorkerResult(
                item=item
            )

        kwargs = request_args(url, item) if request_args is not None else {}

        error, response = request(http, url, **kwargs)

        if error:
            return FetchWorkerResult(
                url=url,
                item=item,
                response=response,
                error=error
            )

        # Forcing urllib3 to read data in thread
        data = response.data

        # Solving mime type
        mimetype, _ = mimetypes.guess_type(url)

        if mimetype is None:
            mimetype = 'text/html'

        # Meta
        meta = {}

        # Guessing extension
        if guess_extension:
            exts = mimetypes.guess_all_extensions(mimetype)

            if not exts:
                ext = '.html'
            elif '.html' in exts:
                ext = '.html'
            else:
                ext = max(exts, key=len)

            meta['mime'] = mimetype
            meta['ext'] = ext

        # Guessing encoding
        if guess_encoding:
            meta['encoding'] = guess_response_encoding(response, data, is_xml=True, use_chardet=True)

        return FetchWorkerResult(
            url=url,
            item=item,
            response=response,
            error=error,
            meta=meta
        )

    # Group resolver
    def grouper(payload):
        if payload.url is None:
            return

        return get_domain_name(payload.url)

    # Thread payload iterator
    def payloads():
        for item in iterator:
            url = item if key is None else key(item)

            if not url:
                yield FetchWorkerPayload(http=http, item=item, url=None)

            # Url cleanup
            url = ensure_protocol(url.strip())

            yield FetchWorkerPayload(
                http=http,
                item=item,
                url=url,
                request_args=request_args
            )

    return imap_unordered(
        payloads(),
        worker,
        threads,
        group=grouper,
        group_parallelism=DEFAULT_GROUP_PARALLELISM,
        group_buffer_size=DEFAULT_GROUP_BUFFER_SIZE,
        group_throttle=throttle
    )

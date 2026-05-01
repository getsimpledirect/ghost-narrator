# MIT License
#
# Copyright (c) 2026 Ayush Naik
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

"""Unit tests for the /tts/jobs filter+sort+paginate helper."""

from __future__ import annotations

import pytest

from app.api.routes.tts import _filter_sort_paginate_jobs


def _job(**overrides):
    """Build a job-data dict with sensible defaults."""
    base = {
        'status': 'queued',
        'created_at': 1000.0,
        'started_at': None,
        'completed_at': None,
        'duration_seconds': None,
        'gcs_uri': None,
        'local_path': None,
        'error': None,
        'text': 'sample article body',
        'gcs_object_path': 'audio/articles/site/job.mp3',
        'site_slug': 'site',
        'resume_count': 0,
    }
    base.update(overrides)
    return base


def _store(*jobs):
    """Build a {job_id: job_data} dict from (id, **kwargs) tuples or dicts."""
    out = {}
    for entry in jobs:
        if isinstance(entry, tuple):
            job_id, kwargs = entry
            out[job_id] = _job(**kwargs)
        else:
            out[entry] = _job()
    return out


class TestBackwardCompatNoFilters:
    """No-arg call returns every job, sorted newest-first by created_at."""

    def test_empty_store_returns_empty(self):
        result, total = _filter_sort_paginate_jobs({})
        assert result == {}
        assert total == 0

    def test_no_filter_returns_all(self):
        store = _store(
            ('a', {'created_at': 100.0}),
            ('b', {'created_at': 200.0}),
            ('c', {'created_at': 50.0}),
        )
        result, total = _filter_sort_paginate_jobs(store)
        assert total == 3
        assert set(result.keys()) == {'a', 'b', 'c'}

    def test_default_sort_is_created_at_desc(self):
        store = _store(
            ('a', {'created_at': 100.0}),
            ('b', {'created_at': 200.0}),
            ('c', {'created_at': 50.0}),
        )
        result, _ = _filter_sort_paginate_jobs(store)
        assert list(result.keys()) == ['b', 'a', 'c']  # newest first


class TestPrefixFilter:
    def test_prefix_match(self):
        store = _store(
            ('backfill-job-1', {}),
            ('backfill-job-2', {}),
            ('regular-job', {}),
        )
        result, total = _filter_sort_paginate_jobs(store, prefix='backfill-')
        assert total == 2
        assert all(k.startswith('backfill-') for k in result)

    def test_prefix_no_matches_returns_empty(self):
        store = _store(('alpha', {}), ('beta', {}))
        result, total = _filter_sort_paginate_jobs(store, prefix='zeta-')
        assert result == {}
        assert total == 0

    def test_prefix_empty_string_matches_all(self):
        store = _store(('a', {}), ('b', {}))
        result, total = _filter_sort_paginate_jobs(store, prefix='')
        assert total == 2


class TestStatusFilter:
    def test_single_status(self):
        store = _store(
            ('a', {'status': 'queued'}),
            ('b', {'status': 'processing'}),
            ('c', {'status': 'completed'}),
        )
        result, total = _filter_sort_paginate_jobs(store, status='queued')
        assert total == 1
        assert 'a' in result

    def test_multiple_statuses_comma_separated(self):
        store = _store(
            ('a', {'status': 'queued'}),
            ('b', {'status': 'processing'}),
            ('c', {'status': 'completed'}),
            ('d', {'status': 'failed'}),
        )
        result, total = _filter_sort_paginate_jobs(store, status='queued,processing')
        assert total == 2
        assert set(result.keys()) == {'a', 'b'}

    def test_status_with_whitespace_around_commas(self):
        store = _store(
            ('a', {'status': 'queued'}),
            ('b', {'status': 'processing'}),
        )
        result, total = _filter_sort_paginate_jobs(store, status=' queued , processing ')
        assert total == 2

    def test_status_no_match_returns_empty(self):
        store = _store(('a', {'status': 'queued'}))
        result, total = _filter_sort_paginate_jobs(store, status='completed')
        assert total == 0
        assert result == {}


class TestSearchQ:
    def test_q_matches_substring_in_id(self):
        store = _store(
            ('backfill-remote-team-salary-guide', {}),
            ('backfill-other-post', {}),
        )
        result, total = _filter_sort_paginate_jobs(store, q='remote-team')
        assert total == 1
        assert 'backfill-remote-team-salary-guide' in result

    def test_q_matches_substring_in_error(self):
        store = _store(
            ('a', {'error': 'CUDA out of memory: 116 MiB'}),
            ('b', {'error': 'Synthesis failed: bad input'}),
        )
        result, total = _filter_sort_paginate_jobs(store, q='CUDA')
        assert total == 1
        assert 'a' in result

    def test_q_is_case_insensitive(self):
        store = _store(('JOB-ABC', {'error': 'Some Error Message'}))
        # Match in id (uppercase data, lowercase query)
        result, _ = _filter_sort_paginate_jobs(store, q='abc')
        assert 'JOB-ABC' in result
        # Match in error (mixed case data, uppercase query)
        result, _ = _filter_sort_paginate_jobs(store, q='ERROR')
        assert 'JOB-ABC' in result

    def test_q_no_match_returns_empty(self):
        store = _store(('a', {'error': 'foo'}))
        result, total = _filter_sort_paginate_jobs(store, q='not-present')
        assert total == 0


class TestSiteSlugFilter:
    def test_exact_match(self):
        store = _store(
            ('a', {'site_slug': 'ghost-founderreality-com'}),
            ('b', {'site_slug': 'ghost-other-com'}),
        )
        result, total = _filter_sort_paginate_jobs(store, site_slug='ghost-founderreality-com')
        assert total == 1
        assert 'a' in result

    def test_no_partial_match(self):
        store = _store(('a', {'site_slug': 'ghost-founderreality-com'}))
        result, total = _filter_sort_paginate_jobs(store, site_slug='founderreality')
        assert total == 0


class TestTimeRangeFilter:
    def test_created_after(self):
        store = _store(
            ('old', {'created_at': 100.0}),
            ('new', {'created_at': 200.0}),
        )
        result, total = _filter_sort_paginate_jobs(store, created_after=150.0)
        assert total == 1
        assert 'new' in result

    def test_created_before(self):
        store = _store(
            ('old', {'created_at': 100.0}),
            ('new', {'created_at': 200.0}),
        )
        result, total = _filter_sort_paginate_jobs(store, created_before=150.0)
        assert total == 1
        assert 'old' in result

    def test_created_range_combined(self):
        store = _store(
            ('a', {'created_at': 50.0}),
            ('b', {'created_at': 150.0}),
            ('c', {'created_at': 250.0}),
        )
        result, total = _filter_sort_paginate_jobs(store, created_after=100.0, created_before=200.0)
        assert total == 1
        assert 'b' in result

    def test_completed_after(self):
        store = _store(
            ('a', {'completed_at': 100.0}),
            ('b', {'completed_at': 200.0}),
            ('c', {'completed_at': None}),  # never completed
        )
        result, total = _filter_sort_paginate_jobs(store, completed_after=150.0)
        assert total == 1
        assert 'b' in result

    def test_time_filter_excludes_jobs_without_field(self):
        # A job with no created_at can't satisfy a created_after filter.
        store = _store(('a', {'created_at': None}))
        result, total = _filter_sort_paginate_jobs(store, created_after=100.0)
        assert total == 0


class TestHasErrorFilter:
    def test_has_error_true(self):
        store = _store(
            ('with-err', {'error': 'something broke'}),
            ('clean', {'error': None}),
            ('also-clean', {'error': ''}),
        )
        result, total = _filter_sort_paginate_jobs(store, has_error=True)
        assert total == 1
        assert 'with-err' in result

    def test_has_error_false(self):
        store = _store(
            ('with-err', {'error': 'broke'}),
            ('clean', {'error': None}),
        )
        result, total = _filter_sort_paginate_jobs(store, has_error=False)
        assert total == 1
        assert 'clean' in result

    def test_has_error_none_does_not_filter(self):
        store = _store(
            ('with-err', {'error': 'broke'}),
            ('clean', {'error': None}),
        )
        result, total = _filter_sort_paginate_jobs(store, has_error=None)
        assert total == 2


class TestCombinedFilters:
    def test_prefix_and_status_combined_and(self):
        store = _store(
            ('backfill-a', {'status': 'queued'}),
            ('backfill-b', {'status': 'completed'}),
            ('regular-a', {'status': 'queued'}),
        )
        result, total = _filter_sort_paginate_jobs(store, prefix='backfill-', status='queued')
        assert total == 1
        assert 'backfill-a' in result

    def test_q_and_has_error_combined(self):
        store = _store(
            ('a', {'error': 'CUDA OOM at 116 MiB'}),
            ('b', {'error': 'some other error'}),
            ('c', {'error': None}),
        )
        result, total = _filter_sort_paginate_jobs(store, q='CUDA', has_error=True)
        assert total == 1
        assert 'a' in result


class TestSorting:
    def test_sort_asc_by_created_at(self):
        store = _store(
            ('a', {'created_at': 200.0}),
            ('b', {'created_at': 100.0}),
            ('c', {'created_at': 300.0}),
        )
        result, _ = _filter_sort_paginate_jobs(store, sort='created_at')
        assert list(result.keys()) == ['b', 'a', 'c']

    def test_sort_desc_by_created_at(self):
        store = _store(
            ('a', {'created_at': 200.0}),
            ('b', {'created_at': 100.0}),
            ('c', {'created_at': 300.0}),
        )
        result, _ = _filter_sort_paginate_jobs(store, sort='-created_at')
        assert list(result.keys()) == ['c', 'a', 'b']

    def test_sort_by_status_alphabetical(self):
        store = _store(
            ('a', {'status': 'processing'}),
            ('b', {'status': 'completed'}),
            ('c', {'status': 'failed'}),
        )
        result, _ = _filter_sort_paginate_jobs(store, sort='status')
        assert list(result.keys()) == ['b', 'c', 'a']

    def test_sort_by_id_alphabetical(self):
        store = _store(
            ('zeta', {}),
            ('alpha', {}),
            ('mike', {}),
        )
        result, _ = _filter_sort_paginate_jobs(store, sort='id')
        assert list(result.keys()) == ['alpha', 'mike', 'zeta']

    def test_sort_by_id_desc(self):
        store = _store(('zeta', {}), ('alpha', {}), ('mike', {}))
        result, _ = _filter_sort_paginate_jobs(store, sort='-id')
        assert list(result.keys()) == ['zeta', 'mike', 'alpha']

    def test_sort_with_none_values_asc_puts_none_last(self):
        # Regression: None-valued jobs must appear at the END in ASC order.
        store = _store(
            ('a', {'completed_at': 100.0}),
            ('b', {'completed_at': None}),
            ('c', {'completed_at': 200.0}),
        )
        result, total = _filter_sort_paginate_jobs(store, sort='completed_at')
        assert total == 3
        # Non-None values sorted asc, then None at the end.
        assert list(result.keys()) == ['a', 'c', 'b']

    def test_sort_with_none_values_desc_puts_none_last(self):
        # Regression: a previous (False, v) / (True, '') sort key produced
        # None-first in DESC, which displaced legitimate newest-first jobs
        # for the default ?sort=-created_at view. Bucketed sort fixes it
        # so None values sit at the end regardless of direction.
        store = _store(
            ('a', {'completed_at': 100.0}),
            ('b', {'completed_at': None}),
            ('c', {'completed_at': 200.0}),
        )
        result, total = _filter_sort_paginate_jobs(store, sort='-completed_at')
        assert total == 3
        # Non-None values sorted desc, then None at the end.
        assert list(result.keys()) == ['c', 'a', 'b']

    def test_sort_only_none_values(self):
        # Pathological case: every job missing the sort field. Should be
        # stable and not raise.
        store = _store(
            ('a', {'completed_at': None}),
            ('b', {'completed_at': None}),
        )
        result, total = _filter_sort_paginate_jobs(store, sort='completed_at')
        assert total == 2
        assert set(result.keys()) == {'a', 'b'}

    def test_unknown_sort_field_raises_value_error(self):
        store = _store(('a', {}))
        with pytest.raises(ValueError, match='Unknown sort field'):
            _filter_sort_paginate_jobs(store, sort='nonexistent')

    def test_unknown_sort_field_with_dash_prefix_raises(self):
        store = _store(('a', {}))
        with pytest.raises(ValueError, match='Unknown sort field'):
            _filter_sort_paginate_jobs(store, sort='-bogus')


class TestPagination:
    def test_limit_only(self):
        store = _store(
            ('a', {'created_at': 100.0}),
            ('b', {'created_at': 200.0}),
            ('c', {'created_at': 300.0}),
        )
        result, total = _filter_sort_paginate_jobs(store, limit=2)
        # Sorted desc, top 2: c, b
        assert total == 3
        assert list(result.keys()) == ['c', 'b']

    def test_offset_only(self):
        store = _store(
            ('a', {'created_at': 100.0}),
            ('b', {'created_at': 200.0}),
            ('c', {'created_at': 300.0}),
        )
        result, total = _filter_sort_paginate_jobs(store, offset=1)
        # Skip newest, get rest: a, b... wait — sorted desc is c,b,a; skip 1 → b, a
        assert total == 3
        assert list(result.keys()) == ['b', 'a']

    def test_limit_and_offset_combined(self):
        store = _store(
            ('a', {'created_at': 100.0}),
            ('b', {'created_at': 200.0}),
            ('c', {'created_at': 300.0}),
            ('d', {'created_at': 400.0}),
        )
        # Sorted desc: d, c, b, a; offset 1 → c, b, a; limit 2 → c, b
        result, total = _filter_sort_paginate_jobs(store, offset=1, limit=2)
        assert total == 4
        assert list(result.keys()) == ['c', 'b']

    def test_offset_beyond_total_returns_empty(self):
        store = _store(('a', {}), ('b', {}))
        result, total = _filter_sort_paginate_jobs(store, offset=10)
        assert total == 2
        assert result == {}

    def test_total_reflects_filter_not_pagination(self):
        # Filter to 5 jobs, paginate to 2; total should still report 5.
        store = _store(
            ('backfill-a', {}),
            ('backfill-b', {}),
            ('backfill-c', {}),
            ('backfill-d', {}),
            ('backfill-e', {}),
            ('regular-1', {}),  # filtered out
        )
        result, total = _filter_sort_paginate_jobs(store, prefix='backfill-', limit=2)
        assert total == 5
        assert len(result) == 2


class TestStripDurableFields:
    def test_text_is_stripped(self):
        store = _store(('a', {'text': 'long article body'}))
        result, _ = _filter_sort_paginate_jobs(store)
        assert 'text' not in result['a']

    def test_gcs_object_path_is_stripped(self):
        store = _store(('a', {'gcs_object_path': 'audio/x.mp3'}))
        result, _ = _filter_sort_paginate_jobs(store)
        assert 'gcs_object_path' not in result['a']

    def test_site_slug_is_stripped(self):
        store = _store(('a', {'site_slug': 'some-site'}))
        result, _ = _filter_sort_paginate_jobs(store)
        assert 'site_slug' not in result['a']

    def test_other_fields_preserved(self):
        store = _store(('a', {'status': 'completed', 'gcs_uri': 'gs://x/y.mp3'}))
        result, _ = _filter_sort_paginate_jobs(store)
        assert result['a']['status'] == 'completed'
        assert result['a']['gcs_uri'] == 'gs://x/y.mp3'

    def test_strip_does_not_mutate_input(self):
        # The in-memory store fallback may return references — strip must not
        # corrupt the underlying record.
        store = _store(('a', {'text': 'original body', 'site_slug': 'ghost'}))
        original_text = store['a']['text']
        original_slug = store['a']['site_slug']

        _filter_sort_paginate_jobs(store)

        assert store['a']['text'] == original_text
        assert store['a']['site_slug'] == original_slug


class TestSiteSlugFilterStillWorksAfterStrip:
    """Regression: the filter must read site_slug from the input even though
    site_slug is stripped from the output. If the filter ran on the stripped
    copy, no jobs would ever match a site_slug query."""

    def test_site_slug_filter_still_works(self):
        store = _store(
            ('a', {'site_slug': 'ghost-founderreality-com'}),
            ('b', {'site_slug': 'ghost-other-com'}),
        )
        result, total = _filter_sort_paginate_jobs(store, site_slug='ghost-founderreality-com')
        assert total == 1
        assert 'a' in result
        # And the site_slug field is not in the response (stripped).
        assert 'site_slug' not in result['a']

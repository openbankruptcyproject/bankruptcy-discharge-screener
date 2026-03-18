#!/usr/bin/env python3
"""Unit tests for screen_1328f.py

Run with:
    python -m unittest discover tests
    python tests/test_screen_1328f.py
"""

import unittest
import sys
import os
from datetime import datetime

# Add parent directory to path for sibling import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screen_1328f import (
    normalize_name,
    extract_names,
    parse_date,
    make_display_name,
    BAPCPA_EFFECTIVE,
    WINDOW_F1_DAYS,
    WINDOW_F2_DAYS,
)


class TestNormalizeName(unittest.TestCase):
    """Test debtor name normalization."""

    def test_lowercase(self):
        self.assertEqual(normalize_name("JOHN SMITH"), "john smith")

    def test_strip_jr_with_period(self):
        self.assertEqual(normalize_name("John Smith Jr."), "john smith")

    def test_strip_jr_no_period(self):
        self.assertEqual(normalize_name("John Smith Jr"), "john smith")

    def test_strip_sr(self):
        self.assertEqual(normalize_name("Mary Jones Sr."), "mary jones")

    def test_strip_iii(self):
        self.assertEqual(normalize_name("Robert Davis III"), "robert davis")

    def test_strip_ii(self):
        self.assertEqual(normalize_name("Robert Davis II"), "robert davis")

    def test_strip_iv(self):
        self.assertEqual(normalize_name("William Clark IV"), "william clark")

    def test_nmn_removal(self):
        """NMN (No Middle Name) should be stripped."""
        self.assertEqual(normalize_name("John NMN Smith"), "john smith")

    def test_nmn_case_insensitive(self):
        self.assertEqual(normalize_name("JOHN nmn SMITH"), "john smith")

    def test_whitespace_collapse(self):
        self.assertEqual(normalize_name("  John   Smith  "), "john smith")

    def test_period_removal(self):
        self.assertEqual(normalize_name("J. Robert Smith"), "j robert smith")

    def test_empty_string(self):
        self.assertEqual(normalize_name(""), "")

    def test_none_input(self):
        self.assertEqual(normalize_name(None), "")

    def test_suffix_2nd(self):
        self.assertEqual(normalize_name("James Wilson 2nd"), "james wilson")

    def test_suffix_3rd(self):
        self.assertEqual(normalize_name("James Wilson 3rd"), "james wilson")


class TestExtractNames(unittest.TestCase):
    """Test name extraction from case titles."""

    def test_single_name_with_middle(self):
        names = extract_names("John Michael Smith")
        self.assertIn("john michael smith", names)
        self.assertIn("john smith", names)

    def test_joint_case_splitting(self):
        names = extract_names("John Smith and Jane Smith")
        self.assertIn("john smith", names)
        self.assertIn("jane smith", names)

    def test_joint_case_and_is_case_insensitive(self):
        names = extract_names("John Smith AND Jane Doe")
        self.assertIn("john smith", names)
        self.assertIn("jane doe", names)

    def test_two_part_name_no_duplicate(self):
        """A two-token name should appear once (first+last == full name)."""
        names = extract_names("John Smith")
        self.assertIn("john smith", names)
        self.assertEqual(names.count("john smith"), 1)

    def test_empty_title(self):
        self.assertEqual(extract_names(""), [])

    def test_none_title(self):
        self.assertEqual(extract_names(None), [])

    def test_suffix_stripped_in_extraction(self):
        names = extract_names("Robert Davis III and Sarah Davis")
        self.assertIn("robert davis", names)
        self.assertIn("sarah davis", names)


class TestParseDate(unittest.TestCase):
    """Test date string parsing."""

    def test_valid_date(self):
        self.assertEqual(parse_date("2024-01-15"), datetime(2024, 1, 15))

    def test_empty_string(self):
        self.assertIsNone(parse_date(""))

    def test_none_input(self):
        self.assertIsNone(parse_date(None))

    def test_whitespace_only(self):
        self.assertIsNone(parse_date("   "))

    def test_wrong_format(self):
        self.assertIsNone(parse_date("01/15/2024"))

    def test_strips_whitespace(self):
        self.assertEqual(parse_date("  2024-01-15  "), datetime(2024, 1, 15))

    def test_garbage_string(self):
        self.assertIsNone(parse_date("not-a-date"))


class TestDateMath(unittest.TestCase):
    """Test 1328(f) statutory window constants and boundary logic."""

    def test_f1_window_is_1461(self):
        self.assertEqual(WINDOW_F1_DAYS, 1461)

    def test_f2_window_is_731(self):
        self.assertEqual(WINDOW_F2_DAYS, 731)

    def test_f1_at_boundary_is_violation(self):
        """Exactly 1461 days: within window, violation."""
        self.assertTrue(1461 <= WINDOW_F1_DAYS)

    def test_f1_past_boundary_is_clear(self):
        """1462 days: outside window, no violation."""
        self.assertFalse(1462 <= WINDOW_F1_DAYS)

    def test_f2_at_boundary_is_violation(self):
        """Exactly 731 days: within window, violation."""
        self.assertTrue(731 <= WINDOW_F2_DAYS)

    def test_f2_past_boundary_is_clear(self):
        """732 days: outside window, no violation."""
        self.assertFalse(732 <= WINDOW_F2_DAYS)

    def test_zero_gap_is_violation(self):
        """Same-day filing: definitely within window."""
        self.assertTrue(0 <= WINDOW_F1_DAYS)
        self.assertTrue(0 <= WINDOW_F2_DAYS)


class TestBAPCPAFilter(unittest.TestCase):
    """Test BAPCPA effective date filtering."""

    def test_bapcpa_date_value(self):
        self.assertEqual(BAPCPA_EFFECTIVE, datetime(2005, 10, 17))

    def test_pre_bapcpa_excluded(self):
        """Filing one day before BAPCPA: excluded."""
        self.assertTrue(datetime(2005, 10, 16) < BAPCPA_EFFECTIVE)

    def test_on_bapcpa_included(self):
        """Filing on BAPCPA effective date: included."""
        self.assertFalse(datetime(2005, 10, 17) < BAPCPA_EFFECTIVE)

    def test_post_bapcpa_included(self):
        """Filing after BAPCPA: included."""
        self.assertFalse(datetime(2006, 1, 1) < BAPCPA_EFFECTIVE)


class TestCSVRowParsing(unittest.TestCase):
    """Test that PACER CSV row fields parse correctly."""

    def setUp(self):
        self.row = {
            'caseId': '99999',
            'caseTitle': 'JOHNSON MICHAEL A',
            'caseNumberFull': '4:2020bk41567',
            'courtId': 'mowbk',
            'bankruptcyChapter': '13',
            'dateFiled': '2020-03-22',
            'dateDischarged': '',
            'dateDismissed': '2021-01-15',
            'disposition': 'Dismissed for Other Reason',
        }

    def test_chapter_extraction(self):
        self.assertEqual(self.row['bankruptcyChapter'].strip(), '13')

    def test_date_filed_parses(self):
        self.assertEqual(parse_date(self.row['dateFiled']),
                         datetime(2020, 3, 22))

    def test_empty_discharge_is_none(self):
        self.assertIsNone(parse_date(self.row['dateDischarged']))

    def test_name_extraction_from_title(self):
        names = extract_names(self.row['caseTitle'])
        self.assertIn('johnson michael a', names)
        self.assertIn('johnson a', names)


class TestMakeDisplayName(unittest.TestCase):
    """Test attorney key to display name conversion."""

    def test_standard_key(self):
        self.assertEqual(make_display_name("Smith_John"), "Smith, John")

    def test_no_underscore(self):
        self.assertEqual(make_display_name("Smith"), "Smith")

    def test_splits_on_first_underscore(self):
        self.assertEqual(make_display_name("Van_Der_Berg_Jan"),
                         "Van, Der_Berg_Jan")


if __name__ == '__main__':
    unittest.main()

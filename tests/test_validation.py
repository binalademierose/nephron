"""
Checks for services/validation.py: what a person may type into the forms.
These need no Flask and no database. Run everything with:   python -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import validation  # noqa: E402


def good_form(**changes):
    form = {"role": "general", "full_name": "Ana Reyes", "email": "ana@example.com", "password": "a-long-enough-phrase",
           "confirm_password": "a-long-enough-phrase", "username": "ana_r", "date_of_birth": "1990-05-14", "country": "Philippines", "province_code": "1300000000",
           "address": "", "avatar": "avatar-1"}
    form.update(changes)
    return form


class EmailTests(unittest.TestCase):
    def test_email_is_trimmed_and_lower_cased(self):
        self.assertEqual(validation.clean_email("  Ana.Reyes@Mail.COM "), "ana.reyes@mail.com")
        self.assertEqual(validation.clean_email(None), "")

    def test_good_and_bad_addresses(self):
        for good in ("a@b.co", "ana.reyes+kidney@mail.example.org"):
            self.assertIsNone(validation.check_email(good), good)
        for bad in ("", "ana", "ana@", "@mail.com", "ana@mail", "ana reyes@mail.com", "a@b@c.com", "x" * 250 + "@mail.com"):
            self.assertIsNotNone(validation.check_email(bad), bad)


class NameTests(unittest.TestCase):
    def test_ordinary_and_unusual_real_names_are_accepted(self):
        for name in ("Ana Reyes", "Ma. Cristina Dela Cruz-Santos", "José Ñoño", "O'Brien", "李雷"):
            self.assertIsNone(validation.check_full_name(name), name)

    def test_empty_short_long_or_letterless_names_are_refused(self):
        for name in ("", "A", "x" * 121, "12345", "Ana\u0000Reyes"):
            self.assertIsNotNone(validation.check_full_name(name), repr(name))

    def test_extra_spaces_are_squeezed(self):
        self.assertEqual(validation.clean_text("  Ana    Reyes \n"), "Ana Reyes")

    def test_greeting_name_and_initials(self):
        self.assertEqual(validation.first_name("Ana Reyes"), "Ana")
        self.assertEqual(validation.initials("Ana Reyes"), "AR")
        self.assertEqual(validation.initials("Ana"), "A")
        self.assertEqual(validation.initials(""), "")
        self.assertEqual(validation.first_name(""), "")

    def test_titles_in_front_of_a_name_are_not_used_to_greet_or_for_initials(self):
        for name, first, letters in (("Dr. Luis Cruz", "Luis", "LC"), ("Atty. Ana Reyes", "Ana", "AR"), ("dr luis cruz", "luis", "LC"),
                                     ("Engr. Dr. Jo Lim", "Jo", "JL"), ("Prof. Kim", "Kim", "K")):
            self.assertEqual(validation.first_name(name), first, name)
            self.assertEqual(validation.initials(name), letters, name)
        self.assertEqual(validation.first_name("Dr."), "Dr.")               # a name that is only a title is kept as it is

    def test_ma_is_half_a_name_so_it_keeps_the_next_word(self):
        self.assertEqual(validation.first_name("Ma. Cristina Dela Cruz"), "Ma. Cristina")
        self.assertEqual(validation.first_name("Ma. Cruz"), "Ma. Cruz")
        self.assertEqual(validation.first_name("Ma."), "Ma.")
        self.assertEqual(validation.initials("Ma. Cristina Dela Cruz"), "MC")


class PasswordTests(unittest.TestCase):
    def test_a_long_plain_phrase_is_fine(self):
        self.assertIsNone(validation.check_password("purple kidneys in spring"))

    def test_length_limits(self):
        self.assertIn("at least 10", validation.check_password("short"))
        self.assertIn("no more than 128", validation.check_password("x-y" * 50))
        self.assertIsNone(validation.check_password("ab3d5f7h9j"))                # exactly 10 characters is enough
        self.assertIsNone(validation.check_password("pass-" * 25 + "x"))          # long is fine up to the limit

    def test_common_and_repetitive_passwords_are_refused(self):
        for weak in ("password123", "PASSWORD123", "1234567890", "qwertyuiop", "aaaaaaaaaaaa", "ababababab"):
            self.assertIn("too easy to guess", validation.check_password(weak) or "", weak)

    def test_the_email_address_may_not_be_used(self):
        self.assertIn("email address", validation.check_password("ana.reyes-2026!", email="ana.reyes@example.com"))
        self.assertIn("email address", validation.check_password("ana@example.com", email="ana@example.com"))
        self.assertIsNone(validation.check_password("ana-2026-long", email="jo@example.com"))   # a short local part is not searched for

    def test_no_composition_rules_are_imposed(self):
        # Long enough and not common is enough: no forced capital letters, digits or symbols.
        self.assertIsNone(validation.check_password("correct horse battery staple"))


class RegistrationTests(unittest.TestCase):
    def test_a_valid_general_registration(self):
        values, errors = validation.validate_registration(good_form(email="  ANA@Example.com "))
        self.assertEqual(errors, {})
        self.assertEqual((values["role"], values["email"], values["professional"]), ("general", "ana@example.com", None))

    def test_every_field_is_checked_and_errors_are_named_by_field(self):
        _, errors = validation.validate_registration({"role": "", "full_name": "", "email": "nope", "password": "x"})
        self.assertEqual(set(errors), {"role", "full_name", "email", "password", "confirm_password", "username", "date_of_birth", "avatar"})

    def test_role_can_only_be_one_of_two_values(self):
        for forged in ("admin", "administrator", "GENERAL", "", "general,professional"):
            _, errors = validation.validate_registration(good_form(role=forged))
            self.assertIn("role", errors, forged)

    def test_professional_details(self):
        values, errors = validation.validate_registration(good_form(role="professional", profession_title="Nephrologist",
                                                                    institution="  City   Hospital ", license_number=" 12-345/A "))
        self.assertEqual(errors, {})
        self.assertEqual(values["professional"], {"profession_title": "Nephrologist", "institution": "City Hospital", "license_number": "12-345/A"})

    def test_professional_optional_fields_may_be_empty(self):
        values, errors = validation.validate_registration(good_form(role="professional", profession_title="Nurse"))
        self.assertEqual(errors, {})
        self.assertEqual(values["professional"], {"profession_title": "Nurse", "institution": None, "license_number": None})

    def test_profession_must_come_from_the_list_and_extras_are_checked(self):
        _, errors = validation.validate_registration(good_form(role="professional", profession_title="Wizard"))
        self.assertIn("profession_title", errors)
        _, errors = validation.validate_registration(good_form(role="professional", profession_title="Nurse", license_number="<script>"))
        self.assertIn("license_number", errors)
        _, errors = validation.validate_registration(good_form(role="professional", profession_title="Nurse", institution="x" * 121))
        self.assertIn("institution", errors)

    def test_professional_fields_are_ignored_for_a_general_user(self):
        values, errors = validation.validate_registration(good_form(profession_title="Wizard", license_number="<script>"))
        self.assertEqual(errors, {})
        self.assertIsNone(values["professional"])

    def test_a_valid_form_returns_the_new_fields_cleaned(self):
        from datetime import date
        values, errors = validation.validate_registration(good_form(username="  Ana_R  ", address="  123 Main St  "))
        self.assertEqual(errors, {})
        self.assertEqual(values["username"], "Ana_R")
        self.assertEqual(values["date_of_birth"], date(1990, 5, 14))
        self.assertEqual(values["address"], "123 Main St")
        self.assertEqual(values["avatar"], "avatar-1")

    def test_address_is_optional(self):
        _, errors = validation.validate_registration(good_form(address=""))
        self.assertEqual(errors, {})


class UsernameTests(unittest.TestCase):
    def test_a_good_username(self):
        self.assertIsNone(validation.check_username("ana_r2"))

    def test_blank_is_refused(self):
        self.assertIsNotNone(validation.check_username(""))

    def test_too_short_or_too_long_is_refused(self):
        self.assertIsNotNone(validation.check_username("ab"))
        self.assertIsNotNone(validation.check_username("a" * 33))

    def test_must_start_with_a_letter(self):
        self.assertIsNotNone(validation.check_username("2cool"))
        self.assertIsNotNone(validation.check_username("_ana"))

    def test_only_letters_numbers_and_underscores(self):
        for bad in ("ana reyes", "ana-reyes", "ana.reyes", "ana@reyes", "<script>"):
            self.assertIsNotNone(validation.check_username(bad), bad)
        self.assertIsNone(validation.check_username("Ana_Reyes123"))


class ConfirmPasswordTests(unittest.TestCase):
    def test_matching_passwords_are_fine(self):
        self.assertIsNone(validation.check_confirm_password("a-long-enough-phrase", "a-long-enough-phrase"))

    def test_a_blank_confirmation_is_refused(self):
        self.assertIsNotNone(validation.check_confirm_password("a-long-enough-phrase", ""))

    def test_a_mismatch_is_refused(self):
        self.assertIsNotNone(validation.check_confirm_password("a-long-enough-phrase", "something-else-entirely"))


class DateOfBirthTests(unittest.TestCase):
    def test_a_valid_adult_date(self):
        from datetime import date
        error, parsed = validation.check_date_of_birth("1990-05-14", today=date(2026, 9, 26))
        self.assertIsNone(error)
        self.assertEqual(parsed, date(1990, 5, 14))

    def test_blank_is_refused(self):
        error, parsed = validation.check_date_of_birth("")
        self.assertIsNotNone(error)
        self.assertIsNone(parsed)

    def test_not_a_real_date_is_refused(self):
        error, parsed = validation.check_date_of_birth("2026-13-40")
        self.assertIsNotNone(error)
        self.assertIsNone(parsed)

    def test_in_the_future_is_refused(self):
        from datetime import date
        error, parsed = validation.check_date_of_birth("2027-01-01", today=date(2026, 9, 26))
        self.assertIsNotNone(error)
        self.assertIsNone(parsed)

    def test_under_18_is_refused(self):
        from datetime import date
        error, parsed = validation.check_date_of_birth("2010-09-27", today=date(2026, 9, 26))     # turns 16 tomorrow
        self.assertIsNotNone(error)
        self.assertIsNone(parsed)

    def test_the_day_before_an_18th_birthday_is_refused_but_the_birthday_itself_is_fine(self):
        from datetime import date
        error, _ = validation.check_date_of_birth("2008-09-27", today=date(2026, 9, 26))          # 18th birthday is tomorrow
        self.assertIsNotNone(error)
        error, parsed = validation.check_date_of_birth("2008-09-26", today=date(2026, 9, 26))     # 18th birthday is today
        self.assertIsNone(error)
        self.assertEqual(parsed, date(2008, 9, 26))

    def test_absurdly_old_is_refused(self):
        error, parsed = validation.check_date_of_birth("1850-01-01")
        self.assertIsNotNone(error)
        self.assertIsNone(parsed)


class AddressTests(unittest.TestCase):
    def test_blank_is_fine(self):
        self.assertIsNone(validation.check_address(""))

    def test_too_long_is_refused(self):
        self.assertIsNotNone(validation.check_address("x" * 256))


class AvatarTests(unittest.TestCase):
    def test_a_listed_avatar_is_fine(self):
        for name in validation.AVATARS:
            self.assertIsNone(validation.check_avatar(name))

    def test_anything_else_is_refused(self):
        for bad in ("", "avatar-9", "../../etc/passwd", "avatar-1.png"):
            self.assertIsNotNone(validation.check_avatar(bad), bad)


class PasswordChangeTests(unittest.TestCase):
    def test_both_fields_are_needed(self):
        errors = validation.validate_password_change("", "", "ana@example.com", "Ana Reyes")
        self.assertEqual(set(errors), {"current_password", "new_password"})

    def test_the_new_password_must_be_different_and_strong(self):
        errors = validation.validate_password_change("old-phrase-here", "old-phrase-here", "ana@example.com", "Ana")
        self.assertIn("different", errors["new_password"])
        errors = validation.validate_password_change("old-phrase-here", "short", "ana@example.com", "Ana")
        self.assertIn("at least 10", errors["new_password"])
        self.assertEqual(validation.validate_password_change("old-phrase-here", "a brand new phrase", "ana@example.com", "Ana"), {})


if __name__ == "__main__":
    unittest.main()

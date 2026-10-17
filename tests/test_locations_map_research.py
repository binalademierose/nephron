"""
Checks for where people live (services/ph_locations.py), the administrator's Pangasinan map
(services/location_heatmap.py) and the de-identified research export (services/research_export.py).
Run everything with:   python -m unittest discover -s tests -v
"""
import csv
import io
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from helpers import AppTestCase  # noqa: E402
from services import location_heatmap, ph_locations, research_export, screening_contract  # noqa: E402
from test_screening_flow import answers  # noqa: E402

NOW = datetime(2026, 10, 9, 2, 0, 0)
LAOAC = next(m["code"] for m in ph_locations.municipalities() if m["name"] == "Laoac")
CAARINGAYAN = next(b["code"] for b in ph_locations.barangays(LAOAC) if b["name"] == "Caaringayan")
METRO_MANILA = next(p["code"] for p in ph_locations.provinces() if p["name"] == "Metro Manila (NCR)")
PANGASINAN = ph_locations.PANGASINAN


class LocationDataTests(unittest.TestCase):
    def test_the_lists_match_the_psgc_counts(self):
        self.assertEqual(len(ph_locations.municipalities()), 48)                    # 44 municipalities + 4 cities
        self.assertEqual(sum(len(ph_locations.barangays(m["code"])) for m in ph_locations.municipalities()), 1364)
        self.assertIn("Pangasinan", {p["name"] for p in ph_locations.provinces()})
        self.assertEqual(ph_locations.describe({"province_code": PANGASINAN, "municipality_code": LAOAC, "barangay_code": CAARINGAYAN}),
                         "Caaringayan, Laoac, Pangasinan")

    def test_only_the_philippines_is_asked_and_only_pangasinan_goes_down_to_the_barangay(self):
        self.assertEqual(ph_locations.validate("USA", {"province_code": PANGASINAN}), (dict.fromkeys(ph_locations.FIELDS), {}))
        self.assertIn("province_code", ph_locations.validate("Philippines", {})[1])
        values, errors = ph_locations.validate("Philippines", {"province_code": METRO_MANILA, "municipality_code": LAOAC})
        self.assertEqual((errors, values["municipality_code"]), ({}, None))                 # a stale town answer is not kept
        self.assertIn("municipality_code", ph_locations.validate("Philippines", {"province_code": PANGASINAN})[1])
        self.assertIn("barangay_code", ph_locations.validate("Philippines", {"province_code": PANGASINAN, "municipality_code": LAOAC})[1])
        values, errors = ph_locations.validate("Philippines", {"province_code": PANGASINAN, "municipality_code": LAOAC, "barangay_code": CAARINGAYAN})
        self.assertEqual((errors, values["barangay_code"]), ({}, CAARINGAYAN))

    def test_a_barangay_from_another_town_is_refused(self):
        other_town = next(m["code"] for m in ph_locations.municipalities() if m["code"] != LAOAC)
        _, errors = ph_locations.validate("Philippines", {"province_code": PANGASINAN, "municipality_code": other_town, "barangay_code": CAARINGAYAN})
        self.assertIn("barangay_code", errors)


class LocationFormTests(AppTestCase):
    def test_registration_saves_the_barangay_of_a_pangasinan_resident(self):
        self.register(country="Philippines", province_code=PANGASINAN, municipality_code=LAOAC, barangay_code=CAARINGAYAN)
        user = self.store.find_by_email("ana@example.com")
        self.assertEqual((user["province_code"], user["municipality_code"], user["barangay_code"]), (PANGASINAN, LAOAC, CAARINGAYAN))

    def test_registration_in_the_philippines_needs_a_province(self):
        response = self.register(country="Philippines")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="province_code-error"', self.text(response))
        self.assertIsNone(self.store.find_by_email("ana@example.com"))

    def test_the_barangay_list_comes_from_the_server(self):
        data = self.client.get(f"/locations/pangasinan/{LAOAC}/barangays").get_json()
        self.assertEqual(data["municipality"], "Laoac")
        self.assertIn({"code": CAARINGAYAN, "name": "Caaringayan"}, data["barangays"])
        self.assertEqual(self.client.get("/locations/pangasinan/999/barangays").status_code, 404)

    def test_an_existing_user_can_add_where_they_live_and_the_dashboard_stops_asking(self):
        browser = self.signed_in(country="Philippines", province_code=METRO_MANILA)
        user_id = self.store.find_by_email("ana@example.com")["user_id"]
        self.store.set_location(user_id, {})
        self.assertIn("Where in the Philippines do you live?", self.text(browser.get("/dashboard")))
        self.assertIn("Where you live", self.text(browser.get("/account")))
        response = self.post("/account/location", {"province_code": PANGASINAN, "municipality_code": LAOAC, "barangay_code": CAARINGAYAN},
                             client=browser, token_from="/account")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.store.find_by_id(user_id)["barangay_code"], CAARINGAYAN)
        self.assertNotIn("Where in the Philippines do you live?", self.text(browser.get("/dashboard")))
        self.assertIn("Saved: Caaringayan, Laoac, Pangasinan", self.text(browser.get("/account")))

    def test_a_professional_records_a_patients_barangay(self):
        professional = self.signed_in(**self.professional_details())
        response = self.post("/patient-records/new", {"full_name": "Pedro Santos", "date_of_birth": "1970-02-02", "gender": "Male", "sex": "Male",
                                                      "country": "Philippines", "province_code": PANGASINAN, "municipality_code": LAOAC,
                                                      "barangay_code": CAARINGAYAN}, client=professional, token_from="/patient-records/new")
        code = response.headers["Location"].split("/")[-2]
        record = self.app.extensions["patient_records_store"].get_by_code(code)
        self.assertEqual(record["barangay_code"], CAARINGAYAN)


def entry(barangay, level, town=LAOAC, province=PANGASINAN):
    return {"province": province, "municipality": town, "barangay": barangay, "level": level}


class HeatmapTests(unittest.TestCase):
    def test_each_municipality_gets_its_totals_and_a_colour(self):
        people = [entry(CAARINGAYAN, "high")] * 3 + [entry(CAARINGAYAN, "low")] + [entry(CAARINGAYAN, None)]
        view = location_heatmap.view(people, "share", "municipality")
        laoac = next(a for a in view["areas"] if a["code"] == LAOAC)
        self.assertEqual((laoac["registered"], laoac["screened"], laoac["high"], laoac["share"]), (5, 4, 3, 75))
        self.assertEqual(laoac["fill"], location_heatmap.RAMPS["risk"][3])               # 75% falls in 60-79%
        self.assertEqual(len(view["areas"]), 48)
        self.assertEqual(view["totals"]["screened"], 4)

    def test_a_place_with_fewer_than_three_screened_shows_no_risk_figure(self):
        view = location_heatmap.view([entry(CAARINGAYAN, "high"), entry(CAARINGAYAN, "high")], "share", "barangay", LAOAC)
        place = next(a for a in view["areas"] if a["code"] == CAARINGAYAN)
        self.assertEqual((place["screened"], place["high"], place["share"], place["state"]), (2, None, None, "suppressed"))
        counts = location_heatmap.view([entry(CAARINGAYAN, "high")] * 2, "screened", "barangay", LAOAC)
        self.assertEqual(next(a for a in counts["areas"] if a["code"] == CAARINGAYAN)["state"], "value")   # a count is not a health fact

    def test_one_towns_barangays_are_zoomed_in_and_only_that_town_is_drawn(self):
        view = location_heatmap.view([], "share", "barangay", LAOAC)
        self.assertEqual(len(view["areas"]), len(ph_locations.barangays(LAOAC)))
        self.assertLess(view["viewbox"][2], 1000)
        self.assertEqual(view["town_name"], "Laoac")

    def test_people_outside_pangasinan_are_counted_by_province(self):
        rows = location_heatmap.other_provinces([entry(None, "high", None, METRO_MANILA)] * 3)
        self.assertEqual((rows[0]["name"], rows[0]["screened"], rows[0]["high"]), ("Metro Manila (NCR)", 3, 3))


class MapAndResearchPagesTests(AppTestCase):
    model = True

    def setUp(self):
        super().setUp()
        self.admin = self.signed_in(email="admin@example.com", full_name="Site Admin")
        self.store.set_admin(self.store.find_by_email("admin@example.com")["user_id"], True)
        self.assessments = self.app.extensions["assessment_store"]

    def screened_person(self, index, barangay=CAARINGAYAN, age=48, extra=None):
        user_id = self.store.create_user({"email": f"p{index}@example.com", "full_name": f"Person {index}", "role": "general", "professional": None,
                                          "country": "Philippines", "province_code": PANGASINAN, "municipality_code": LAOAC,
                                          "barangay_code": barangay}, "h", NOW)
        catalog = screening_contract.load_catalog()
        values, inputs, errors = screening_contract.validate_answers(catalog, answers(Age=str(age)))
        assert not errors, errors
        inputs.update({"Gender": "Female", **(extra or {})})
        self.assessments.add_assessment(user_id, {"assessment_type": "preliminary", "probability": 0.8, "classification": "high",
                                                  "threshold_used": 0.46, "model_version": "v1", "assessed_at": NOW}, inputs)
        return user_id

    def test_the_map_page_draws_pangasinan_with_a_legend_and_drills_into_a_town(self):
        for i in range(3):
            self.screened_person(i)
        page = self.text(self.admin.get("/admin/map"))
        self.assertIn("Pangasinan map", page)
        self.assertEqual(page.count('class="map-area"'), 48)
        self.assertIn("Laoac: 3 screened, 3 at higher risk (100%)", page)
        self.assertIn("Fewer than 3 screened - hidden for privacy", page)
        town = self.text(self.admin.get(f"/admin/map?level=barangay&town={LAOAC}"))
        self.assertIn("Caaringayan, Laoac: 3 screened", town)
        self.assertNotIn("Person 0", town)                                                 # never a name
        everything = self.text(self.admin.get("/admin/map?level=barangay&metric=screened"))
        drawable = len([b for b in ph_locations.map_data()["barangays"] if b["path"]])          # 9 barangays have no outline in the source
        self.assertEqual(everything.count('class="map-area"'), drawable)

    def test_only_an_administrator_can_open_the_map_and_the_research_data(self):
        member = self.signed_in(email="member@example.com", username="member_x")
        for path in ("/admin/map", "/admin/research-data", "/admin/research-data/preliminary.csv"):
            self.assertEqual(member.get(path).status_code, 403, path)

    def test_the_export_holds_only_predictors_with_no_identity_and_old_ages_capped(self):
        self.screened_person(1, age=95)
        self.screened_person(2)
        self.screened_person(2 + 100, extra={"height_cm": 160})
        page = self.text(self.admin.get("/admin/research-data"))
        self.assertIn("No identity", page)
        response = self.admin.get("/admin/research-data/preliminary.csv")
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        header, body = rows[0], rows[1:]
        self.assertEqual(header, screening_contract.feature_names(screening_contract.load_catalog()))
        for leaked in ("Gender", "height_cm", "weight_kg", "user_id", "assessment_id", "probability", "classification", "email"):
            self.assertNotIn(leaked, header)
        self.assertEqual(len(body), 3)
        ages = sorted(int(row[header.index("Age")]) for row in body)
        self.assertEqual(ages[-1], research_export.AGE_CAP)
        text = response.get_data(as_text=True)
        self.assertNotIn("Person", text)
        self.assertNotIn("@example.com", text)
        self.assertTrue(any(e["action"] == "research_export" for e in self.app.extensions["activity_store"].recent()))

    def test_latest_per_person_by_default_every_screening_on_request(self):
        user_id = self.screened_person(1)
        _, inputs, _ = screening_contract.validate_answers(screening_contract.load_catalog(), answers())
        self.assessments.add_assessment(user_id, {"assessment_type": "preliminary", "probability": 0.2, "classification": "low",
                                                  "threshold_used": 0.46, "model_version": "v1", "assessed_at": NOW}, inputs)
        latest = list(csv.reader(io.StringIO(self.admin.get("/admin/research-data/preliminary.csv").get_data(as_text=True))))
        every = list(csv.reader(io.StringIO(self.admin.get("/admin/research-data/preliminary.csv?all=1").get_data(as_text=True))))
        self.assertEqual((len(latest) - 1, len(every) - 1), (1, 2))
        self.assertEqual(self.admin.get("/admin/research-data/other.csv").status_code, 404)


if __name__ == "__main__":
    unittest.main()

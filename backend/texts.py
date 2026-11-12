"""All texts the API writes for people: warnings and advice, in English and Uzbek."""
from __future__ import annotations

from .climate import BASELINE, PROJECTION_YEAR

LANGS = ("en", "uz")

WARN = {
    "en": {
        "disabled": "{name} is switched off. Analysis that needs it was skipped.",
        "power_failed": "NASA POWER did not respond and there is no saved data near this point. Climate, crop and rotation analysis was skipped. Try a point nearby or try again in a moment.",
        "power_fallback": "NASA POWER did not respond. Showing saved data of a point {km} km away. Numbers do not exactly match this place.",
        "power_monthly": "NASA POWER daily data did not arrive, so monthly data is used. Heat days, frost dates and dry spells are approximate or missing.",
        "not_land": "This point looks like open water or ice: NASA has no soil data here. The crop results below have no practical meaning.",
        "layer_down": "{name} did not respond. Its map layers are hidden.",
        "soil_down": "{name} did not respond. Soil is set to '{soil}'. Choose your soil type in the field passport for a better result.",
        "forecast_down": "{name} did not respond. The weekly outlook uses what usually happens on these dates (NASA data, 2011-2025) instead of a forecast.",
        "json_failed": "{name} did not respond and was left out.",
        "conflict": "In '{name}' the seasons of {a} and {b} overlap by {days} days. This rotation cannot be grown as written.",
    },
    "uz": {
        "disabled": "{name} o'chirilgan. Unga tayanadigan tahlil o'tkazib yuborildi.",
        "power_failed": "NASA POWER javob bermadi va bu joy yaqinida saqlangan ma'lumot yo'q. Iqlim, ekin va rotatsiya tahlili o'tkazib yuborildi. Yaqin atrofdagi boshqa nuqtani tanlang yoki birozdan keyin urinib ko'ring.",
        "power_fallback": "NASA POWER javob bermadi. {km} km uzoqlikdagi saqlangan nuqta ma'lumoti ko'rsatilmoqda. Raqamlar aynan shu joyga mos emas.",
        "power_monthly": "NASA POWER kunlik ma'lumoti kelmadi, shuning uchun oylik ma'lumot ishlatildi. Issiq kunlar, sovuq sanalari va qurg'oqchil davrlar taxminiy yoki yo'q.",
        "not_land": "Bu nuqta suv yoki muzlikka o'xshaydi: NASA'da bu yer uchun tuproq ma'lumoti yo'q. Quyidagi ekin natijalari amaliy ma'noga ega emas.",
        "layer_down": "{name} javob bermadi. Uning xarita qatlamlari yashirildi.",
        "soil_down": "{name} javob bermadi. Tuproq '{soil}' deb olindi. Aniqroq natija uchun dala pasportida tuproq turini tanlang.",
        "forecast_down": "{name} javob bermadi. Haftalik ko'rsatkich prognoz o'rniga shu sanalarda odatda nima bo'lishiga (NASA ma'lumoti, 2011-2025) tayanadi.",
        "json_failed": "{name} javob bermadi va tahlilga qo'shilmadi.",
        "conflict": "'{name}' rotatsiyasida {a} va {b} mavsumlari {days} kun ustma-ust tushadi. Bu rotatsiyani shu ko'rinishda ekib bo'lmaydi.",
    },
}

DISCLAIMER = {
    "en": "Climate numbers come from NASA POWER on a grid of about 50 km, so nearby fields get the same climate. Water need is computed for regional weather; over irrigated land the real value is usually somewhat lower (FAO-56, Annex 6), so use the numbers to compare crops, rotations and periods. Crop thresholds, soil index and income are transparent rules, not measurements or a yield forecast.",
    "uz": "Iqlim raqamlari NASA POWER'dan, taxminan 50 km to'rda olingan, shuning uchun yaqin dalalar bir xil iqlim oladi. Suv ehtiyoji hududiy ob-havo uchun hisoblangan; sug'oriladigan yer ustida haqiqiy qiymat odatda biroz past bo'ladi (FAO-56, 6-ilova), shu sababli raqamlarni ekinlar, rotatsiyalar va davrlarni solishtirish uchun ishlating. Ekin chegaralari, tuproq indeksi va daromad ochiq qoidalar, o'lchov yoki hosil prognozi emas.",
}

_ADVICE = {
    "en": {
        "best_is_current": "For your priorities, your current rotation '{cur}' is already the best of the {n} compared (score {score} of 100).",
        "best": "For your priorities, '{best}' scores highest: {score} of 100 against {cur_score} for your current '{cur}'.",
        "best_water_less": "It needs about {m3} m3/ha less water per year ({pct}% less).",
        "best_water_more": "It needs about {m3} m3/ha more water per year ({pct}% more).",
        "best_income": "Estimated income changes by {usd:+.0f} USD/ha per year.",
        "best_soil": "Soil health index: {a} against {b}.",
        "stable": "It came first in {wins} of {n} weather years (2011-2025), so the choice is robust.",
        "unstable": "It came first in only {wins} of {n} weather years: '{runner}' is close. Treat the two as equal and decide by what matters most to you.",
        "warming": "Average temperature here is {d:+.1f} °C compared with {b0}-{b1} ({trend:+.2f} °C per decade{sig}). If the trend continues, about {proj:.1f} °C by {py} (likely range {lo:.1f} to {hi:.1f}).",
        "rain": "Yearly precipitation changed by {pct:+.0f}% ({base:.0f} to {recent:.0f} mm). Year-to-year differences are large, so this alone is not a reliable trend.",
        "rain_sig": "Yearly precipitation changed by {pct:+.0f}% ({base:.0f} to {recent:.0f} mm), a statistically significant trend.",
        "demand": "The air now takes {d:+.0f} mm more water per year from fields (reference evapotranspiration {base:.0f} to {recent:.0f} mm).",
        "hot_days": "Days hotter than 35 °C: {base:.0f} per year before, {recent:.0f} now.",
        "frost": "The last spring frost now comes around {recent} (before: {base}), and the frost-free season is {d:+.0f} days longer.",
        "frost_shorter": "The last spring frost now comes around {recent} (before: {base}), and the frost-free season is {d:.0f} days shorter.",
        "sowing": "{crop}: the suitable sowing date moved from {base} to {recent} ({d:+.0f} days).",
        "crop_stress": "{crop}: in {share:.0%} of recent years there were at least {limit} days above {thr} °C in its sensitive stage (before: {before:.0%}).",
        "now_dry": "The last 30 days brought {rain} mm of rain, drier than {pct}% of the same dates on record.",
        "now_wet": "The last 30 days brought {rain} mm of rain, wetter than {pct}% of the same dates on record.",
        "next_rain": "Forecast ({src}): next rain around {date} ({mm} mm); {week} mm expected in the next 7 days.",
        "no_rain": "Forecast ({src}): no rain of 1 mm or more in the next {n} days.",
        "usual_rain": "On these dates it usually rains within {days} days (in {prob:.0%} of years within a week).",
        "week": "{crop} is in the field now: about {mm} mm of water needed this week, {m3} m3/ha with your irrigation method.",
        "sig": ", statistically significant",
    },
    "uz": {
        "best_is_current": "Sizning ustuvorliklaringiz bo'yicha hozirgi rotatsiyangiz '{cur}' solishtirilgan {n} tadan eng yaxshisi (100 dan {score} ball).",
        "best": "Sizning ustuvorliklaringiz bo'yicha '{best}' eng yuqori ball oldi: 100 dan {score}, hozirgi '{cur}' esa {cur_score}.",
        "best_water_less": "U yiliga gektariga taxminan {m3} m3 kam suv talab qiladi ({pct}% kam).",
        "best_water_more": "U yiliga gektariga taxminan {m3} m3 ko'p suv talab qiladi ({pct}% ko'p).",
        "best_income": "Taxminiy daromad yiliga gektariga {usd:+.0f} AQSh dollariga o'zgaradi.",
        "best_soil": "Tuproq salomatligi indeksi: {a}, hozirgisida {b}.",
        "stable": "U {n} ta ob-havo yilining (2011-2025) {wins} tasida birinchi bo'ldi, ya'ni tanlov barqaror.",
        "unstable": "U {n} ta ob-havo yilining faqat {wins} tasida birinchi bo'ldi: '{runner}' unga yaqin. Ikkalasini teng deb hisoblab, o'zingiz uchun muhimiga qarab tanlang.",
        "warming": "Bu yerda o'rtacha harorat {b0}-{b1} yillarga nisbatan {d:+.1f} °C ga o'zgargan (har o'n yilda {trend:+.2f} °C{sig}). Trend davom etsa, {py} yilga borib taxminan {proj:.1f} °C (ehtimoliy oraliq {lo:.1f} dan {hi:.1f} gacha).",
        "rain": "Yillik yog'in {pct:+.0f}% ga o'zgargan ({base:.0f} dan {recent:.0f} mm ga). Yillar orasidagi farq katta, shuning uchun buning o'zi ishonchli trend emas.",
        "rain_sig": "Yillik yog'in {pct:+.0f}% ga o'zgargan ({base:.0f} dan {recent:.0f} mm ga), bu statistik jihatdan ishonchli trend.",
        "demand": "Havo dalalardan yiliga {d:+.0f} mm ko'proq suv olmoqda (etalon bug'lanish {base:.0f} dan {recent:.0f} mm ga).",
        "hot_days": "35 °C dan issiq kunlar: avval yiliga {base:.0f} ta, hozir {recent:.0f} ta.",
        "frost": "Oxirgi bahorgi sovuq hozir taxminan {recent} da (avval: {base}), sovuqsiz mavsum {d:+.0f} kunga uzaygan.",
        "frost_shorter": "Oxirgi bahorgi sovuq hozir taxminan {recent} da (avval: {base}), sovuqsiz mavsum {d:.0f} kunga qisqargan.",
        "sowing": "{crop}: qulay ekish sanasi {base} dan {recent} ga siljigan ({d:+.0f} kun).",
        "crop_stress": "{crop}: so'nggi yillarning {share:.0%} qismida nozik davrida {thr} °C dan issiq kunlar {limit} tadan oshgan (avval: {before:.0%}).",
        "now_dry": "Oxirgi 30 kunda {rain} mm yomg'ir yog'di. Bu shu sanalar tarixining {pct}% idan quruqroq.",
        "now_wet": "Oxirgi 30 kunda {rain} mm yomg'ir yog'di. Bu shu sanalar tarixining {pct}% idan seryog'inroq.",
        "next_rain": "Prognoz ({src}): keyingi yomg'ir taxminan {date} da ({mm} mm); kelgusi 7 kunda {week} mm kutilmoqda.",
        "no_rain": "Prognoz ({src}): kelgusi {n} kunda 1 mm va undan ko'p yomg'ir kutilmaydi.",
        "usual_rain": "Bu sanalarda odatda {days} kun ichida yomg'ir yog'adi (yillarning {prob:.0%} ida bir hafta ichida).",
        "week": "{crop} hozir dalada: bu hafta taxminan {mm} mm suv kerak, sizning sug'orish usulingizda gektariga {m3} m3.",
        "sig": ", statistik jihatdan ishonchli",
    },
}


_MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "uz": ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"],
}


def day(lang: str, value: str) -> str:
    """'04-10' or '2026-04-10' -> '10 Apr' / '10-aprel'."""
    month, dom = int(value[-5:-3]), int(value[-2:])
    return f"{dom} {_MONTHS[lang][month - 1]}" if lang == "en" else f"{dom}-{_MONTHS[lang][month - 1]}"


def advice(lang: str, climate: dict, crops: list, rotations: dict, now: dict) -> list[dict]:
    t = _ADVICE[lang]
    out = []

    def add(group, severity, text):
        out.append({"group": group, "severity": severity, "text": text})

    def name(obj):
        return obj["name"].get(lang, obj["name"]["en"])

    # 1. rotation decision
    items = rotations.get("items") or []
    if items:
        best = next(it for it in items if it["id"] == rotations["best_id"])
        cur = next(it for it in items if it["is_current"])
        n = rotations["years_replayed"]
        if best["id"] == cur["id"]:
            parts = [t["best_is_current"].format(cur=name(cur), n=len(items), score=best["scores"]["total"])]
        else:
            vs = best["vs_current"]
            parts = [t["best"].format(best=name(best), score=best["scores"]["total"],
                                      cur=name(cur), cur_score=cur["scores"]["total"])]
            if vs["water_pct"] is None:
                pass  # current rotation needs no irrigation water, so a percentage has no meaning
            elif vs["water_m3_ha"] >= 100:
                parts.append(t["best_water_less"].format(m3=vs["water_m3_ha"], pct=abs(vs["water_pct"])))
            elif vs["water_m3_ha"] <= -100:
                parts.append(t["best_water_more"].format(m3=-vs["water_m3_ha"], pct=abs(vs["water_pct"])))
            parts.append(t["best_income"].format(usd=vs["income_usd_ha"]))
            parts.append(t["best_soil"].format(a=best["soil"]["index"], b=cur["soil"]["index"]))
        add("rotation", "tip", " ".join(parts))
        runner = next((it for it in items if it["id"] != best["id"] and not it["conflicts"]), None)
        if rotations["clear_winner"] or not runner:
            add("rotation", "info", t["stable"].format(wins=best["wins"], n=n))
        else:
            add("rotation", "warning", t["unstable"].format(wins=best["wins"], n=n, runner=name(runner)))

    # 2. climate shift
    s = climate["shift"]
    tm = s["t_mean"]
    if tm["delta"] is not None and abs(tm["delta"]) >= 0.3 and tm["projection"]:
        p = tm["projection"]
        add("climate", "warning" if tm["delta"] >= 1 else "info", t["warming"].format(
            d=tm["delta"], b0=BASELINE[0], b1=BASELINE[1], trend=tm["trend_per_decade"],
            sig=t["sig"] if tm["trend_significant"] else "", proj=p["value"], py=PROJECTION_YEAR,
            lo=p["low"], hi=p["high"]))
    pr = s["precip_mm"]
    if pr["delta_pct"] is not None and abs(pr["delta_pct"]) >= 5:
        key = "rain_sig" if pr["trend_significant"] else "rain"
        add("climate", "warning" if pr["delta_pct"] <= -10 else "info",
            t[key].format(pct=pr["delta_pct"], base=pr["baseline"], recent=pr["recent"]))
    et = s["et0_mm"]
    if et["delta"] is not None and et["delta"] >= 20:
        add("climate", "warning", t["demand"].format(d=et["delta"], base=et["baseline"], recent=et["recent"]))
    hd = s.get("hot_days")
    if hd and hd["delta"] is not None and hd["delta"] >= 3:
        add("climate", "warning" if hd["delta"] >= 7 else "info", t["hot_days"].format(base=hd["baseline"], recent=hd["recent"]))
    fr = climate.get("frost")
    if fr and abs(fr["frost_free_change_days"]) >= 5:
        change = fr["frost_free_change_days"]
        add("climate", "info", t["frost" if change > 0 else "frost_shorter"].format(
            recent=day(lang, fr["recent"]["last_spring_frost"]),
            base=day(lang, fr["baseline"]["last_spring_frost"]), d=abs(change)))

    # 3. crops
    for c in crops:
        sow = c.get("sowing")
        if sow and abs(sow["shift_days"]) >= 5:
            add("crops", "info", t["sowing"].format(crop=name(c), base=day(lang, sow["baseline"]), recent=day(lang, sow["recent"]),
                                                    d=sow["shift_days"]))
    for c in sorted(crops, key=lambda c: -c["recent"]["heat_years_share"])[:2]:
        if c["recent"]["heat_years_share"] >= 0.2 and c["baseline"]:
            add("crops", "critical" if c["recent"]["heat_years_share"] >= 0.5 else "warning", t["crop_stress"].format(
                crop=name(c), share=c["recent"]["heat_years_share"], limit=c["heat_rule"]["limit_days"],
                thr=c["heat_rule"]["tmax_c"], before=c["baseline"]["heat_years_share"]))

    # 4. now
    rec, fc, out_ = now.get("recent"), now.get("forecast"), now.get("outlook")
    if rec and rec["rain_percentile"] is not None:
        if rec["rain_percentile"] <= 25:
            add("now", "warning", t["now_dry"].format(rain=rec["rain_mm"], pct=100 - rec["rain_percentile"]))
        elif rec["rain_percentile"] >= 75:
            add("now", "info", t["now_wet"].format(rain=rec["rain_mm"], pct=rec["rain_percentile"]))
    if fc:
        if fc["next_rain_date"]:
            add("now", "info", t["next_rain"].format(src=fc["source"], date=day(lang, fc["next_rain_date"]),
                                                     mm=fc["next_rain_mm"], week=fc["rain_7d_mm"]))
        else:
            add("now", "warning", t["no_rain"].format(src=fc["source"], n=fc["horizon_days"]))
    elif out_:
        add("now", "info", t["usual_rain"].format(days=out_["days_to_rain"]["p50"],
                                                  prob=out_["rain_within_7d_probability"]))
    for w in now.get("week") or []:
        if w["net_mm"] >= 1:
            add("now", "tip", t["week"].format(crop=name(w), mm=w["net_mm"], m3=w["m3_ha"]))
    return out


# ---------- can crops grow here at all? ----------

SUIT = {
    "en": {
        "head_unsuitable": "Crops cannot be grown here",
        "head_limited": "Farming here is possible only with limits",
        "head_ok": "This point can be farmed",
        "sub_unsuitable": "This point is not available as a field, so crop and rotation advice was skipped.",
        "sub_limited": "Read the limits below before trusting the crop and rotation numbers.",
        "sub_ok": "No building, road, water or ice was found here, and the climate allows a growing season.",
        "todo_unsuitable": "What to do: click open land nearby (a field or orchard) or search for a farming district.",
        "land_unknown": "OpenStreetMap did not answer, so land cover was not checked; only the climate was judged.",
        "building": ("There is a building here{name}",
                     "A house or other building covers the ground, so there is no open soil for roots, rain or sunlight. Fields must be open land."),
        "road": ("This is a road or asphalt{name}",
                 "Asphalt and concrete seal the ground: water and air do not reach the soil, and nothing can be planted on a road."),
        "transport": ("This is a railway or airfield{name}",
                      "Transport land is paved or packed hard and is not allowed for farming."),
        "urban": ("This is built-up land (town, industry, cemetery){name}",
                  "The land is set aside for housing, industry or other non-farm use, and most of the soil is covered. Field analysis makes sense only for farmland."),
        "park": ("This is a park or sports ground{name}",
                 "It is public green or sports space, not farmland, so crops are not planted here."),
        "water": ("This is a lake, river or reservoir{name}",
                  "The ground is under water. Roots cannot breathe under water, so field crops cannot grow. Choose a field on the shore."),
        "sea": ("This is open sea or ocean",
                "There is no land at this point: no soil, no address, and NASA POWER reports no soil wetness here. Crops need land."),
        "no_soil": ("No land soil here: water or ice sheet",
                    "NASA POWER has no root-zone soil wetness for this point, which happens over open water and ice sheets. Crops need soil."),
        "glacier": ("This is a glacier{name}",
                    "The ground is covered by permanent ice: there is no soil and no warm season."),
        "rock": ("This is bare rock or scree{name}",
                 "There is no soil layer to hold roots and water."),
        "sand": ("This is loose sand or dunes{name}",
                 "Moving sand holds almost no water or nutrients and buries seedlings."),
        "wetland": ("This is a wetland or marsh{name}",
                    "The soil is waterlogged most of the year: roots of most field crops rot (rice is the exception). Draining wetlands also harms nature."),
        "forest": ("This is forest{name}",
                   "Farming would need the trees cut down, which is not recommended; the numbers below assume open land."),
        "too_cold": ("Too cold: no growing season",
                     "Even the warmest month averages only {t} °C (NASA POWER, 2011-2025). Crops need months warmer than 10 °C to grow; here there are none (tundra or ice climate)."),
        "short_season": ("Cold climate with a very short season",
                         "Only {n} month(s) a year average 10 °C or more (warmest {t} °C). Only fast, cold-hardy crops (barley, potato, cabbage) or greenhouses can work; cotton and other warm crops will not ripen."),
        "hyper_arid": ("Hyper-arid desert",
                       "Rain is {rain} mm a year while the air can evaporate {et0} mm (aridity {ai}, below 0.05). Rain-fed farming is impossible; every crop needs full irrigation from a reliable water source."),
        "extreme_heat": ("Extreme heat",
                         "In the hottest month the average daily maximum is {t} °C. Above about 45 °C most crops cannot flower; sow in the cooler months only."),
        "farmland": ("OpenStreetMap marks this as farmland{name}", "The land is already used for crops, gardens or pasture ({osm})."),
        "facts": "Average temperature {t} °C (warmest: {wm}, {tw} °C; coldest: {cm}, {tc} °C) · rain {rain} mm/year · elevation {elev} m · {n} month(s) at 10 °C or warmer",
    },
    "uz": {
        "head_unsuitable": "Bu yerda ekin ekib bo'lmaydi",
        "head_limited": "Bu yerda dehqonchilik faqat cheklov bilan mumkin",
        "head_ok": "Bu nuqtada ekin ekish mumkin",
        "sub_unsuitable": "Bu nuqta dala sifatida mavjud emas, shuning uchun ekin va rotatsiya tavsiyasi berilmadi.",
        "sub_limited": "Ekin va rotatsiya raqamlariga ishonishdan oldin quyidagi cheklovlarni o'qing.",
        "sub_ok": "Bu yerda bino, yo'l, suv yoki muz topilmadi, iqlim esa o'sish mavsumiga imkon beradi.",
        "todo_unsuitable": "Nima qilish kerak: yaqin atrofdagi ochiq yerni (dala yoki bog') bosing yoki qishloq xo'jaligi tumanini qidiring.",
        "land_unknown": "OpenStreetMap javob bermadi, shuning uchun yer qoplami tekshirilmadi; faqat iqlim baholandi.",
        "building": ("Bu yerda bino turibdi{name}",
                     "Uy yoki boshqa inshoot yerni yopib turibdi: ildiz, yomg'ir va quyosh uchun ochiq tuproq yo'q. Dala ochiq yer bo'lishi kerak."),
        "road": ("Bu yo'l yoki asfalt{name}",
                 "Asfalt va beton yerni yopadi: suv va havo tuproqqa yetib bormaydi, yo'l ustiga hech narsa ekib bo'lmaydi."),
        "transport": ("Bu temir yo'l yoki aerodrom{name}",
                      "Transport yerlari qoplangan yoki zichlangan, dehqonchilik uchun ruxsat etilmaydi."),
        "urban": ("Bu qurilgan hudud (shahar, sanoat, qabriston){name}",
                  "Yer turar-joy, sanoat yoki boshqa qishloq xo'jaligidan tashqari maqsad uchun ajratilgan, tuprog'i asosan yopilgan. Dala tahlili faqat qishloq xo'jaligi yerlari uchun ma'noli."),
        "park": ("Bu park yoki sport maydoni{name}",
                 "Bu jamoat yashil yoki sport hududi, qishloq xo'jaligi yeri emas, bu yerga ekin ekilmaydi."),
        "water": ("Bu ko'l, daryo yoki suv ombori{name}",
                  "Yer suv ostida. Suv ostida ildiz nafas ololmaydi, shuning uchun dala ekinlari o'smaydi. Qirg'oqdagi dalani tanlang."),
        "sea": ("Bu ochiq dengiz yoki okean",
                "Bu nuqtada quruqlik yo'q: tuproq ham, manzil ham yo'q, NASA POWER bu yer uchun tuproq namligini bermaydi. Ekin uchun quruqlik kerak."),
        "no_soil": ("Bu yerda quruqlik tuprog'i yo'q: suv yoki muz qatlami",
                    "NASA POWER bu nuqta uchun ildiz qatlami namligini bermaydi, bu ochiq suv va muz qatlamlari ustida bo'ladi. Ekin uchun tuproq kerak."),
        "glacier": ("Bu muzlik{name}",
                    "Yer doimiy muz bilan qoplangan: tuproq ham, issiq mavsum ham yo'q."),
        "rock": ("Bu ochiq tosh yoki tosh uyumi{name}",
                 "Ildiz va suvni ushlab turadigan tuproq qatlami yo'q."),
        "sand": ("Bu ko'chma qum yoki barxan{name}",
                 "Ko'chma qum deyarli suv va oziq ushlamaydi, nihollarni ko'mib yuboradi."),
        "wetland": ("Bu botqoqlik{name}",
                    "Tuproq yil bo'yi suvga to'yingan: ko'pchilik dala ekinlarining ildizi chiriydi (sholi bundan mustasno). Botqoqni quritish tabiatga ham zarar."),
        "forest": ("Bu o'rmon{name}",
                   "Dehqonchilik uchun daraxtlarni kesish kerak bo'ladi, bu tavsiya etilmaydi; quyidagi raqamlar ochiq yer uchun hisoblangan."),
        "too_cold": ("Juda sovuq: o'sish mavsumi yo'q",
                     "Eng issiq oyning o'rtacha harorati ham atigi {t} °C (NASA POWER, 2011-2025). Ekinlar o'sishi uchun 10 °C dan issiq oylar kerak; bu yerda bunday oy yo'q (tundra yoki muz iqlimi)."),
        "short_season": ("Sovuq iqlim, mavsum juda qisqa",
                         "Yilda atigi {n} oy o'rtacha 10 °C va undan issiq (eng issiq oy {t} °C). Faqat tez pishadigan, sovuqqa chidamli ekinlar (arpa, kartoshka, karam) yoki issiqxona mumkin; paxta kabi issiqsevar ekinlar pishmaydi."),
        "hyper_arid": ("O'ta qurg'oqchil cho'l",
                       "Yog'in yiliga {rain} mm, havo esa {et0} mm suvni bug'lata oladi (qurg'oqchilik indeksi {ai}, 0.05 dan past). Lalmi dehqonchilik mumkin emas; har bir ekin ishonchli manbadan to'liq sug'orishni talab qiladi."),
        "extreme_heat": ("Haddan tashqari issiq",
                         "Eng issiq oyda kunduzgi o'rtacha maksimum {t} °C. Taxminan 45 °C dan yuqorida ko'pchilik ekinlar gullay olmaydi; faqat salqin oylarda eking."),
        "farmland": ("OpenStreetMap bu yerni qishloq xo'jaligi yeri deb belgilagan{name}", "Yer allaqachon ekin, bog' yoki yaylov uchun ishlatiladi ({osm})."),
        "facts": "O'rtacha harorat {t} °C (eng issiq: {wm}, {tw} °C; eng sovuq: {cm}, {tc} °C) · yog'in {rain} mm/yil · balandlik {elev} m · {n} oy 10 °C va undan issiq",
    },
}


def suitability(lang: str, s: dict) -> dict:
    """Adds readable texts to a suitability.judge() result."""
    from .suitability import month_name

    t = SUIT[lang]
    items = []
    for r in s["reasons"]:
        title, detail = t[r["code"]]
        nm = f" ({r['name']})" if r.get("name") else ""
        fmt = {k: v for k, v in r.items() if k not in ("code", "level", "name")}
        items.append({"code": r["code"], "level": r["level"],
                      "title": title.format(name=nm), "detail": detail.format(**fmt)})
    c = s["climate"]
    facts = t["facts"].format(
        t=c["t_mean_c"], wm=month_name(c["warmest_month"], lang), tw=c["warmest_t_c"],
        cm=month_name(c["coldest_month"], lang), tc=c["coldest_t_c"], rain=int(c["rain_mm"]),
        elev=int(c["elevation_m"] or 0), n=c["growing_months"]) if c else None
    return {
        **s,
        "headline": t["head_" + s["status"]],
        "summary": t["sub_" + s["status"]],
        "todo": t["todo_unsuitable"] if s["status"] == "unsuitable" else None,
        "note": None if s["land"]["checked"] else t["land_unknown"],
        "facts": facts,
        "items": items,
    }


# ---------- what this region grows ----------

REGION = {
    "en": {
        "title": "Region: {country} — what is grown",
        "title_local": "{region}, {country} — what farmers grow here",
        "source_local": "Share of the cropland within about 75 km of the point (same province), MapSPAM 2020 (IFPRI). Income = national yield × producer price (FAOSTAT).",
        "title_unknown": "Crops for this point",
        "source": "Share of the country's harvested cropland, FAOSTAT {y0}–{y1}. Income = national yield × producer price.",
        "unknown": "The country of this point is not known (OpenStreetMap did not answer), so the world's most common crops were checked against the climate here.",
        "summary": "Of the main crops of {country}, {n} can be grown at this point; the rotations below are built only from them.",
        "summary_none": "None of the main crops of {country} ripen reliably at this point, so no rotation could be built.",
        "suggested": "Not common in {country}, added for soil health (a legume fixes nitrogen): {crops}.",
        "here_yes": "grows here", "here_no": "not here", "here_na": "not modelled",
        "reasons": {
            "frost": "frost after sowing in most years",
            "season_too_cold": "the season is too cold for it to ripen",
            "too_warm_for_winter": "winters are too warm for a winter crop",
            "no_data": "not enough weather data",
        },
        "origin": {"typical": "typical here", "local": "local crops", "suggested": "with a new crop",
                   "reference": "reviewed reference"},
        "src": {"country": "country data", "subregion": "regional average", "world": "world average",
                "default": "app default"},
    },
    "uz": {
        "title": "Hudud: {country} — nima ekiladi",
        "title_local": "{region}, {country} — fermerlar bu yerda nima ekadi",
        "source_local": "Nuqta atrofidagi taxminan 75 km (shu viloyat ichida) ekin maydoni ulushi, MapSPAM 2020 (IFPRI). Daromad = milliy hosildorlik × sotish narxi (FAOSTAT).",
        "title_unknown": "Bu nuqta uchun ekinlar",
        "source": "Davlatdagi yig'ib olingan ekin maydonidagi ulush, FAOSTAT {y0}–{y1}. Daromad = milliy hosildorlik × sotish narxi.",
        "unknown": "Bu nuqtaning davlati aniqlanmadi (OpenStreetMap javob bermadi), shuning uchun dunyoda eng ko'p ekiladigan ekinlar shu joy iqlimi bilan tekshirildi.",
        "summary": "{country}: asosiy ekinlardan {n} tasi shu nuqtada o'sadi; quyidagi rotatsiyalar faqat ulardan tuzildi.",
        "summary_none": "{country}: asosiy ekinlardan hech biri shu nuqtada ishonchli pishmaydi, shuning uchun rotatsiya tuzib bo'lmadi.",
        "suggested": "{country} bo'yicha keng tarqalmagan, tuproq salomatligi uchun qo'shildi (dukkakli ekin azot to'playdi): {crops}.",
        "here_yes": "bu yerda o'sadi", "here_no": "bu yerda o'smaydi", "here_na": "modellashtirilmagan",
        "reasons": {
            "frost": "ko'p yillarda ekishdan keyin sovuq uradi",
            "season_too_cold": "mavsum pishishi uchun juda sovuq",
            "too_warm_for_winter": "kuzgi ekin uchun qish juda iliq",
            "no_data": "ob-havo ma'lumoti yetarli emas",
        },
        "origin": {"typical": "bu yerda odatiy", "local": "mahalliy ekinlar", "suggested": "yangi ekin bilan",
                   "reference": "tekshirilgan namuna"},
        "src": {"country": "davlat ma'lumoti", "subregion": "mintaqa o'rtachasi", "world": "dunyo o'rtachasi",
                "default": "ilova qiymati"},
    },
}

# FAOSTAT names of common crops that the app does not simulate, for the Uzbek list
FAO_UZ = {
    "Apples": "Olma", "Grapes": "Uzum", "Sugar cane": "Shakarqamish", "Coffee, green": "Qahva",
    "Cassava, fresh": "Kassava", "Yams": "Yams", "Oil palm fruit": "Moyli palma", "Oats": "Suli", "Rye": "Javdar",
    "Triticale": "Tritikale", "Linseed": "Zig'ir", "Safflower seed": "Maxsar", "Buckwheat": "Grechka",
    "Cow peas, dry": "Sigir no'xati", "Peas, dry": "Quruq no'xat", "Lupins": "Lyupin", "Olives": "Zaytun",
    "Cocoa beans": "Kakao", "Coconuts, in shell": "Kokos", "Bananas": "Banan", "Sweet potatoes": "Batat",
    "Other vegetables, fresh n.e.c.": "Boshqa sabzavotlar", "Other fruits, n.e.c.": "Boshqa mevalar",
    "Watermelons": "Tarvuz", "Cabbages": "Karam", "Carrots and turnips": "Sabzi va sholg'om",
    "Apricots": "O'rik", "Cherries": "Gilos", "Walnuts, in shell": "Yong'oq", "Almonds, in shell": "Bodom",
    "Tea leaves": "Choy", "Natural rubber in primary forms": "Kauchuk", "Sesame seed": "Kunjut",
}


def region(lang: str, p: dict) -> dict:
    from .agro import CROPS

    t = REGION[lang]
    nm = lambda cid: CROPS[cid]["name"][lang]  # noqa: E731
    c, loc = p["country"], p.get("local")
    cname = c["name"] if c else (loc["country"] if loc else None)
    place = loc["region"] if loc else cname
    top = []
    for row in p["top"]:
        if row["crop_id"]:
            label = nm(row["crop_id"])
        elif row.get("label"):  # MapSPAM crop the app does not simulate
            label = row["label"][lang]
        else:  # FAOSTAT item the app does not simulate
            label = FAO_UZ.get(row["name_en"], row["name_en"]) if lang == "uz" else row["name_en"]
        here = {"yes": "here_yes", "no": "here_no", None: "here_na"}[row["here"]]
        top.append({"name": label, "share": row["share"], "crop_id": row["crop_id"], "here": row["here"],
                    "here_text": t[here], "reason": t["reasons"].get(row["reason"]) if row["reason"] else None})
    grown_main = [r for r in p["top"] if r["here"] == "yes"]
    if c or loc:
        summary = t["summary"].format(country=place, n=len(grown_main)) if p["grown_here"] else t["summary_none"].format(country=place)
    else:
        summary = t["unknown"]
    econ = {cid: {**v, "source_text": t["src"][v["source"]], "name": nm(cid)} for cid, v in p["economics"].items()}
    return {
        **p,
        "title": t["title_local"].format(region=loc["region"], country=cname) if loc
        else t["title"].format(country=cname) if c else t["title_unknown"],
        "source_text": t["source_local"] if loc
        else t["source"].format(y0=c["years"][0], y1=c["years"][1]) if c else None,
        "summary": summary,
        "suggested_text": t["suggested"].format(country=place or "", crops=", ".join(nm(x) for x in p["suggested"])) if p["suggested"] and (c or loc) else None,
        "top": top,
        "not_here": [{"id": x["id"], "name": nm(x["id"]), "reason": t["reasons"].get(x["reason"], x["reason"])} for x in p["not_here"]],
        "economics": econ,
        "origin_text": t["origin"],
    }

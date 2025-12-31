# Common ADR Country Overrides

This is a reference list of common ADRs (American Depositary Receipts) that need country overrides.

## How to Add These

Copy the entries you need to `config/country_overrides.json` under the "overrides" section.

## Chinese Companies (ADRs)

```json
"US01609W1027": {
  "country_code": "CN",
  "name": "Alibaba Group Holding Ltd",
  "note": "Chinese e-commerce company ADR"
},
"US05606L1008": {
  "country_code": "CN",
  "name": "BYD Co Ltd",
  "note": "Chinese EV manufacturer ADR"
},
"US0567521085": {
  "country_code": "CN",
  "name": "Baidu Inc",
  "note": "Chinese search engine ADR"
},
"US62914V1061": {
  "country_code": "CN",
  "name": "NIO Inc",
  "note": "Chinese EV manufacturer ADR"
},
"US70450Y1038": {
  "country_code": "CN",
  "name": "Pinduoduo Inc",
  "note": "Chinese e-commerce ADR"
},
"US88160R1014": {
  "country_code": "CN",
  "name": "Tencent Holdings Ltd",
  "note": "Chinese tech conglomerate ADR"
},
"US98980G1022": {
  "country_code": "CN",
  "name": "JD.com Inc",
  "note": "Chinese e-commerce ADR"
},
"US92556H2067": {
  "country_code": "CN",
  "name": "Vipshop Holdings Ltd",
  "note": "Chinese online retailer ADR"
},
"US98418T1060": {
  "country_code": "CN",
  "name": "XPeng Inc",
  "note": "Chinese EV manufacturer ADR"
},
"US23291J1060": {
  "country_code": "CN",
  "name": "Daqo New Energy Corp",
  "note": "Chinese solar manufacturer ADR"
}
```

## Taiwan Companies (ADRs)

```json
"US8740391003": {
  "country_code": "TW",
  "name": "Taiwan Semiconductor",
  "note": "Taiwanese chip manufacturer ADR"
},
"US92647K1007": {
  "country_code": "TW",
  "name": "United Microelectronics",
  "note": "Taiwanese semiconductor ADR"
}
```

## Indian Companies (ADRs)

```json
"US4581401001": {
  "country_code": "IN",
  "name": "ICICI Bank Ltd",
  "note": "Indian bank ADR"
},
"US4642872349": {
  "country_code": "IN",
  "name": "Infosys Ltd",
  "note": "Indian IT services ADR"
},
"US92677D1000": {
  "country_code": "IN",
  "name": "Wipro Ltd",
  "note": "Indian IT services ADR"
}
```

## Brazilian Companies (ADRs)

```json
"US66980N1028": {
  "country_code": "BR",
  "name": "Nu Holdings Ltd",
  "note": "Brazilian fintech ADR"
},
"US7421301040": {
  "country_code": "BR",
  "name": "Petrobras",
  "note": "Brazilian oil company ADR"
},
"US92343E1029": {
  "country_code": "BR",
  "name": "Vale SA",
  "note": "Brazilian mining company ADR"
}
```

## Korean Companies (ADRs)

```json
"US7960502018": {
  "country_code": "KR",
  "name": "Samsung Electronics",
  "note": "Korean electronics ADR"
},
"US49456B1017": {
  "country_code": "KR",
  "name": "KB Financial Group",
  "note": "Korean bank ADR"
}
```

## Japanese Companies (ADRs)

```json
"US8766685024": {
  "country_code": "JP",
  "name": "Toyota Motor Corp",
  "note": "Japanese automaker ADR"
},
"US8473305030": {
  "country_code": "JP",
  "name": "Sony Group Corp",
  "note": "Japanese electronics ADR"
},
"US6178051036": {
  "country_code": "JP",
  "name": "Mitsubishi UFJ Financial",
  "note": "Japanese bank ADR"
}
```

## European Companies (NYSE/NASDAQ Listed)

Most European companies listed in the US keep their home country ISIN, but some exceptions:

```json
"US82968B1035": {
  "country_code": "CH",
  "name": "Smith & Nephew",
  "note": "Swiss medical devices (if US listing)"
}
```

## How to Find ISINs

1. **From your CSV import**: The ISIN is in the data
2. **From broker statements**: Listed for each security
3. **From financial websites**: 
   - Yahoo Finance: Stock → Statistics → ISIN
   - Bloomberg: Security details
   - OpenFIGI: https://www.openfigi.com

## Quick Add Script

To add multiple overrides quickly:

```python
from config.country_resolver import CountryResolver

resolver = CountryResolver()

# Add multiple overrides
overrides_to_add = [
    ("US01609W1027", "CN", "Alibaba Group", "Chinese e-commerce ADR"),
    ("US05606L1008", "CN", "BYD Co Ltd", "Chinese EV manufacturer ADR"),
    ("US8740391003", "TW", "Taiwan Semiconductor", "Taiwanese chip manufacturer ADR"),
]

for isin, country, name, note in overrides_to_add:
    resolver.add_override(isin, country, name, note, save=True)
    print(f"Added: {name} ({isin}) → {country}")
```

## Notes

- **ADRs** always have US ISINs (starting with "US")
- **GDRs** (Global Depositary Receipts) may have different country codes
- **Check your actual ISINs** - companies may have multiple listings with different ISINs
- **Verify country codes** using ISO 3166-1 alpha-2 standard

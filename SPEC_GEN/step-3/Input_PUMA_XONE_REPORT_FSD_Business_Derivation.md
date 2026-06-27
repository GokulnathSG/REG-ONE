# Functional Specification Document – PUMA_XONE_REPORT

## 1. Purpose
This Functional Specification Document provides business-readable derivation logic for the target table `PUMA_XONE_REPORT`. The lineage has been interpreted recursively until the earliest available parent business source or rule-created value based on the provided specification and TDD extracts.

## 2. Source and Processing Overview
The report primarily consolidates trade, currency, amount, counterparty, security, market and client-category information from `CBR_DTM_TRADE`, reference/product lookup tables, reporting/version layers, normalization expressions, and final `EXPTRANS2` output formatting.

## 3. Field-Level Business Derivation Logic

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0001`
1. The field is populated from a fixed reporting header generated in `EXP_NRM.0001`. The source value is not taken from a trade source table; it is constructed as the literal string `1 0001 C AIM.06`.
2. There is no lookup or conditional selection for this field. The value is retained unchanged after it is created in the normalization layer.
3. The final fixed value flows through `EXPTRANS2.0001` and is populated into `PUMA_XONE_REPORT.O_0001` as the reporting attribute for code `0001`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0583`
1. The starting point is the sequence generator `SEQ_UNIQUE.NEXTVAL`, which provides a unique sequential value for each output record.
2. There is no business lookup or conditional transformation applied to the generated sequence value. The source value is carried forward without business transformation.
3. The generated sequence flows through `EXP_NRM.i_0583` and `EXPTRANS2.i_0583` and is finally populated into `PUMA_XONE_REPORT.O_0583`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0003`
1. The business derivation starts with trade source fields from `CBR_DTM_TRADE`, mainly `ID_SCHEME`, `FIRST_CURRENCY`, `SECOND_CURRENCY`, `FAR_LEG_FIRST_NOT_AMNT`, `FAR_LEG_SECOND_NOT_AMNT`, `EXCHANGED_CURRENCY`, and `PF_BOOKINGENTITYID`.
2. The system first standardizes `ID_SCHEME`: when the scheme is `XoneInventory`, it is treated as `XoneInventory_Fx`. For FX inventory trades, the reporting currency is determined by checking the first and second currencies and their far-leg notional amounts. If the trade is not FX inventory, `EXCHANGED_CURRENCY` is used as the reporting currency.
3. The system determines the booking-entity ISO payment residence by looking up `RF_DPR_TCLIBDR.CA3ISOPAYRES` using `CODTRS = PF_BOOKINGENTITYID` through `LKP_TCLIBDR_0003`.
4. The final classification is assigned as follows: `1` when the booking entity residence is `ITA` and the selected currency is `EUR`; `2` when the residence is `ITA` and currency is not `EUR`; `3` when the residence is not `ITA` and currency is `EUR`; otherwise `4`. This value flows through reporting/version/normalization layers and is populated into `PUMA_XONE_REPORT.O_0003`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0125`
1. The derivation starts from counterparty and country attributes in `CBR_DTM_TRADE`, principally `COUNTERP_TRADEPARTYID` and `CP_CTRCODE`.
2. The system determines an adjusted counterparty identifier by looking up `RF_DPR_TCLIBDR.CODETBGES` using `CODTRS = COUNTERP_TRADEPARTYID`. This provides the reference/group identifier to use when adjustment is required.
3. The adjustment logic applies when `CP_CTRCODE` equals `022`. In that case, the system checks the delivering entity by looking up `RF_DPR_TCLIBDR.CA3ISOPAYRES` using `CODTRS = o_CODETBGESDEL`. If the delivering entity resolves to Italy (`ITA`), the delivering-entity adjusted identifier `o_Adjusted_CounterpartyID_del` is selected; otherwise the previously resolved `Adjusted_CounterpartyID` is retained.
4. For counterparties where `CP_CTRCODE` is not `022`, no adjustment is applied and `COUNTERP_TRADEPARTYID` is retained unchanged. The finalized identifier flows as `ADJUSTED_COUNTERPARTYID` and is populated into `PUMA_XONE_REPORT.O_0125`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0147`
1. The derivation classifies the trade/security for reporting. It uses `CBR_DTM_TRADE.EXCHANGED_CURRENCY` together with product attributes retrieved from `CBR_DTM_PRODUCT` and security mapping attributes from `PUMA_SEC_TYP_XONE`.
2. The system enriches the trade by looking up product details using `TRADEID = TRADEID1` and `FUNCTIONALDATE = FUNCTIONAL_DATE`, returning `OPTIONTYPE` and `PRODUCT_SPECIFIC_TYPE_CODE`. It also looks up security mapping using `X_ONE_NAME = INSTRUMENTNAME` and `RED_ISDA = ISDAPRODUCTNAME`, returning `PUMA_SECURITY`.
3. If the security lookup identifies FX option or bond option combinations, the system assigns reporting security codes such as `0200501` for call options, `0200502` for put options, `0200303`/`0200304` for bond option cash exercise cases, and `0200204`/`0200205` for swap-style products depending on whether `EXCHANGED_CURRENCY` is `EUR`.
4. If the lookup-based security result is missing or blank, the system falls back to `Var_Security`, derived from `PRODUCT_SPECIFIC_TYPE_CODE`, `OPTIONTYPE`, and `EXCHANGED_CURRENCY`. The final security classification flows into `PUMA_XONE_REPORT.O_0147`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0456`
1. The field is populated from a fixed normalized value in `EXP_NRM`. The business value is built as reporting code `0456` with data type indicator `D`.
2. The reporting payload value `v_0456` is generated as `LPAD(1,16,'0')`, meaning the value `1` is left-padded with zeros to a 16-character reporting format.
3. There are no source-table dependencies, lookups, or conditional rules. The formatted value is populated into `PUMA_XONE_REPORT.O_0456`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0461`
1. The derivation starts from trade scheme, currency, amount, and trade-date attributes in `CBR_DTM_TRADE`: `ID_SCHEME`, `FIRST_CURRENCY`, `SECOND_CURRENCY`, far-leg notional amounts, `EXCHANGED_CURRENCY`, `TRADE_DATE`, `CLEAN_AMOUNT`, `EXCHANGEDAMOUNT`, and `NOMINAL_AMOUNT`.
2. The system determines the correct amount to report. For `XoneInventory_Fx` trades, it derives an FX amount from the far-leg notional amount associated with the relevant currency. For other trades, the selected amount depends on the lookup-driven `AMOUNT_TYPE`: `CLEAN_AMOUNT`, `EXCHANGEDAMOUNT`, or `NOMINAL_AMOUNT`.
3. Amounts are converted to EUR-equivalent reporting basis by dividing absolute source amounts by `EUR_CONVERSION_VALUE`. The conversion value is `1` when the selected currency is `EUR`; otherwise it is retrieved through the currency-rate lookup using selected currency and `TRADE_DATE`.
4. The resulting amount is formatted to two decimal places, the decimal separator is removed, and the value is left-padded to 16 characters. The final formatted amount is populated into `PUMA_XONE_REPORT.O_0461`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0562`
1. The field is populated from a reference-driven activity flag rather than directly from a trade amount or party field.
2. The system uses `LKP_CBR_FBL_ACTIVITYMAP_TD` to retrieve `CBR_FBL_ACTIVITYMAP_TD.FLAG` where `OBJECT_NAME = TRADING_DESK_First`. This lookup identifies the configured trading-desk activity nature for the report.
3. The returned `FLAG` value is assigned to `o_SGCIB_NATURE` and then populated into `PUMA_XONE_REPORT.O_0562`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0567`
1. The field is populated from the trade direction held in `CBR_DTM_TRADE.TRADE_DIRECTION`.
2. The system converts the business direction into the required reporting code: `Buy` is mapped to `1`, and `Sell` is mapped to `2`.
3. No lookup is used. The mapped value is populated into `PUMA_XONE_REPORT.O_0567`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0621`
1. The field is populated from a hardcoded normalized reporting line generated in `EXP_NRM.0621`.
2. The output string uses reporting code `0621`, data type indicator `D`, and value `0`. The commented alternative also indicates `0`, so there is no material alternative business rule.
3. The fixed value is carried forward through `EXPTRANS2.0621` and populated into `PUMA_XONE_REPORT.O_0621`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_0741`
1. The derivation starts from `CBR_DTM_TRADE.TRADEMARKET_TYPE`, `CP_PARTY_TYPECODE`, `CP_CTRCODE`, `COUNTERP_TRADEPARTYID`, and issuer/counterparty reference attributes.
2. The system first standardizes market type: `OverTheCounter` becomes `227`, `Organized` becomes `110`, and any other value defaults to `227`.
3. The system enriches counterparty and country information using reference lookups, including `LKP_TCLIBDR`, `LKP_TPAYBDR`, and `LKP_PUMA_0741`. The `PUMA_0741` lookup uses `CLIENT_TYPE = CP_PARTY_TYPECODE` and `CTR_CODE = CP_CTRCODE`; the payment-country lookup uses `CA3ISOPAY` to obtain EU/non-EU indicators.
4. The reporting value is selected by regional logic: Italy maps to the `IT` value; non-Italy EU countries map to `NON_IT_EU`; non-EU countries map to `NON_IT_NON_EU`; and OTC market cases may fall back to `884`. The final mapped category is populated into `PUMA_XONE_REPORT.O_0741`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_1206`
1. The derivation reuses the security classification logic built from `CBR_DTM_TRADE.EXCHANGED_CURRENCY`, `CBR_DTM_PRODUCT` product attributes, and `PUMA_SEC_TYP_XONE` security mappings.
2. The system retrieves `OPTIONTYPE` and `PRODUCT_SPECIFIC_TYPE_CODE` from `CBR_DTM_PRODUCT` using trade and functional-date matching, and retrieves `PUMA_SECURITY`, `X_ONE_NAME`, and `RED_ISDA` using the instrument-name and ISDA-product-name mapping.
3. Lookup-derived security rules are applied first for FX options, bond options, swaps, and related product families. If they do not produce a usable value, fallback product-specific rules assign the reporting security class.
4. The resulting PUMA security classification is then used for downstream amount/security reporting and is populated into `PUMA_XONE_REPORT.O_1206`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_1363`
1. The field is populated from hardcoded normalized reporting value `1 1363 D 002` generated in `EXP_NRM.1363`.
2. There are no source-table fields, lookups, or conditions. The value is retained unchanged and populated into `PUMA_XONE_REPORT.O_1363`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_1365`
1. The field is populated from `CBR_DTM_TRADE.TRADEMARKET_TYPE`.
2. The system maps `OverTheCounter` to reporting code `227`, maps `Organized` to `110`, and defaults all other values to `227`.
3. The final standardized market-type code is populated into `PUMA_XONE_REPORT.O_1365`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_1378`
1. The field is populated from hardcoded normalized reporting value `1 1378 D 98` generated in `EXP_NRM.1378`.
2. No lookup or conditional logic is applied. The value is retained unchanged and populated into `PUMA_XONE_REPORT.O_1378`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_1539`
1. The derivation starts from `CBR_DTM_TRADE.CP_PARENTGROUPID`, `COUNTERP_TRADEPARTYID`, and reference classification `RF_DPR_TCLIBDR.CODNTT`.
2. The system enriches the counterparty by looking up `RF_DPR_TCLIBDR` using counterparty/entity keys and effective-date filters. This returns the counterparty nature/category code used for reporting.
3. The field applies parent-group and counterparty-category business classification to determine the final reporting group code. The provided document includes the lineage and lookup dependencies, but the full expression text is not completely explicit in the readable extract.
4. The final derived category is populated into `PUMA_XONE_REPORT.O_1539`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_2065`
1. The field is populated from hardcoded normalized reporting value `1 2065 D 2` generated in `EXP_NRM.2065`.
2. No source-table dependency, lookup, or condition is applied. The value is retained unchanged and populated into `PUMA_XONE_REPORT.O_2065`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_2066`
1. The field is populated from hardcoded normalized reporting value `1 2066 D 103` generated in `EXP_NRM.2066`.
2. No source-table dependency, lookup, or condition is applied. The value is retained unchanged and populated into `PUMA_XONE_REPORT.O_2066`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_2192`
1. The field derives the counterparty/client category from master reference data. The system uses the adjusted counterparty identifier as the key to look up `CBR_PUMA_MASTERO_BDR_DATA` through `LKP_2192_Mstro` using `BDRID = o_Adjusted_CounterpartyID`.
2. The lookup returns `MIFID_CATEGORY` and `EXCEPTION_CATEGORY`. If `MIFID_CATEGORY` is null, empty, or marked as `null`, the system assigns `000`.
3. For available MIFID information, the system maps the client into reporting categories such as `500`, `511`, `512`, or `520`, with exception-category logic used to refine the classification.
4. The final client-category value flows as `Del_o_2192` and is populated into `PUMA_XONE_REPORT.O_2192`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_2193`
1. The field is populated from hardcoded normalized reporting value `1 2193 D 7` generated in `EXP_NRM.2193`.
2. There are no business-changing transformations. The value is retained unchanged and populated into `PUMA_XONE_REPORT.O_2193`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_2252`
1. The field is populated from the counterparty parent group held in `CBR_DTM_TRADE.CP_PARENTGROUPID`.
2. The system identifies whether the counterparty belongs to the specific parent group `000002539`. If it matches, the value is set to `1`; otherwise it is set to `0`.
3. The resulting binary indicator is populated into `PUMA_XONE_REPORT.O_2252`.

### Business Derivation Logic for `PUMA_XONE_REPORT.O_2474`
1. The field is populated from `CBR_DTM_TRADE.TRADEID`.
2. The source value is carried forward without business transformation through the reporting and normalization layers.
3. The trade identifier is populated into `PUMA_XONE_REPORT.O_2474` to retain trade-level traceability in the output report.

### Business Derivation Logic for `PUMA_XONE_REPORT.PRODUCTID`
1. The field is populated from `CBR_DTM_TRADE.PRODUCTID`.
2. The source value is carried forward without business transformation.
3. The product identifier is populated into `PUMA_XONE_REPORT.PRODUCTID` for product-level traceability.

### Business Derivation Logic for `PUMA_XONE_REPORT.V_SEC_TYPE_exclude`
1. The derivation uses security mapping attributes `X_ONE_NAME` and `RED_ISDA` from `PUMA_SEC_TYP_XONE`, retrieved through `LKP_SEC_TYPE` using `X_ONE_NAME = INSTRUMENTNAME` and `RED_ISDA = ISDAPRODUCTNAME`.
2. The system checks whether the instrument belongs to configured excluded security families, such as certificate/bond-leg/bond-style instruments listed in the expression.
3. If the configured exclusion condition is met, the target is assigned `EXCLUDE_TRADE`; otherwise it is assigned `NA`. The result is populated into `PUMA_XONE_REPORT.V_SEC_TYPE_exclude`.

### Business Derivation Logic for `PUMA_XONE_REPORT.FLAG`
1. The field is a data-quality/control indicator generated after the main report fields are derived. It depends recursively on multiple required reporting fields, including identifiers, security classification, counterparty adjustment, amount, market, and client-category outputs.
2. The system checks whether mandatory derived values such as `0001`, `i_0583`, `i_0003`, `i_0125`, `i_0147`, amount/market/category fields, and related fields are null or outside accepted values.
3. The client-category rule also checks whether `i_2192` is one of the allowed categories `000`, `510`, or `520`; non-allowed categories contribute to the flag condition.
4. If any required value fails the validation rule, `FLAG` is set to `1`; otherwise it is set to `0`. The final value is populated into `PUMA_XONE_REPORT.FLAG`.

### Business Derivation Logic for `PUMA_XONE_REPORT.COMMENTS`
1. The comments field is a consolidated explanation/control message generated from the same recursive dependencies used for validation: security type, client category, market classification, counterparty adjustment, amount formatting, and mandatory report fields.
2. The system evaluates a chain of comment variables from `v_cmt1` through `v_cmt22`. Each variable adds or carries forward comment text when a related business field is missing, inconsistent, excluded, or outside expected reporting values.
3. The comment logic uses lookups and derived fields from `LKP_SEC_TYPE`, `LKP_PRODUCT`, `LKP_TCLIBDR`, `LKP_PUMA_0741`, `LKP_TPAYBDR`, `LKP_2192_Mstro`, and `lkp_amt_type` to explain issues found in security, party, country, amount, and client-category derivations.
4. The final assembled comment value `v_cmt22` is populated into `PUMA_XONE_REPORT.COMMENTS` to support business review and exception handling.

### Business Derivation Logic for `PUMA_XONE_REPORT.QUARTER`
1. The field is populated from the workflow/session parameter `$$QUATER` in `EXPTRANS2.QUARTER`.
2. There is no lookup or conditional business logic. The configured reporting quarter value is populated into `PUMA_XONE_REPORT.QUARTER`.

### Business Derivation Logic for `PUMA_XONE_REPORT.YEAR`
1. The field is populated from the workflow/session parameter `$$FILE_DATE` in `EXPTRANS2.YEAR`.
2. There is no lookup or conditional business logic. The configured reporting year/file-date value is populated into `PUMA_XONE_REPORT.YEAR`.

### Business Derivation Logic for `PUMA_XONE_REPORT.MONTH`
1. The field is populated from the workflow/session parameter `$$MONTH` in `EXPTRANS2.MONTH`.
2. There is no lookup or conditional business logic. The configured reporting month value is populated into `PUMA_XONE_REPORT.MONTH`.

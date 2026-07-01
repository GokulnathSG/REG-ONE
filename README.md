# REG-ONE


<img width="245" height="786" alt="image" src="https://github.com/user-attachments/assets/44f074c5-97a9-4052-8ee7-f49571a8cab8" />


Python Steps
step-1: Convert Informatica XML To JSON: 
python 01_informatica_xml_to_json.py input_XML/PUMA/wf_CBR_AIM06_XONE.XML input_json/PUMA_XONE/wf_CBR_AIM06_XONE.json

step-2: Worflow,Session,Mapping and Transformation as JSON:
python 02_overview.py input_XML/PUMA/wf_CBR_AIM06_XONE.XML -o input_json/PUMA_XONE/wf_CBR_AIM06_XONE_Overview.json

step-3: Convert the JSON to Word-doc:
python 03_overview_to_docs.py input_json/PUMA_XONE/wf_CBR_AIM06_XONE_Overview.json docs/PUMA_XONE/

step-4: Generate Technical details as JSON format (more than 1 mapping)
python 04_fsd_briefing_builder.py -i input_json/PUMA_XONE/wf_CBR_AIM06_XONE.json --all-mappings --lineage-only --lineage-out-dir output/JSON/PUMA_XONE/

step-5: Convert the technical JSON to Word-doc:
python 05_json_to_word_updated.py output/JSON/PUMA_XONE/ docs/PUMA_XONE/
 
step-6: Convert the all-mapping doc into Single WORD doc:
python 06_consolidate_mulit.py --mode doc -i docs/PUMA_XONE -o docs/PUMA_XONE/PUMA_Xone_Consolidated_TDD.docx --title "PUMA Xone Consolidated Docs"


python Transformation_wise.py --subject-area M2R_DTM --workflow WF_DTM_MMTR --config config.json --output output/workflow_all_transformations.xlsx


python Transformation_wise.py --subject-area M2R_DTM --workflow WF_DTM_MMTR --mapping M_DTM_MMTR_ELIGIBILITY --config config.json --output mapping_transformations.xlsx




python Transformation_wise_updated.py \
  --subject-area M2R_DTM \
  --workflow WF_DTM_MMTR \
  --transformation-name EXP_VALIDATE_DATA


  python Transformation_wise_updated.py \
  --subject-area M2R_DTM \
  --workflow WF_DTM_MMTR \
  --transformation-name EXP_VALIDATE_DATA \
  --transformation-name TGT_CUSTOMER


  python Transformation_wise_updated.py \
  --subject-area M2R_DTM \
  --workflow WF_DTM_MMTR \
  --transformation-name "EXP_VALIDATE_DATA,TGT_CUSTOMER,LKP_ACCOUNT"
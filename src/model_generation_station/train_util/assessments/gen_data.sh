#!/bin/bash
# ABANDON HOPE ALL YE WHO ENTER HERE
# Used by Khan Academy to download the last week of assessments and filter them
# into something our model can use
# Use: ./gen_data.py path/to/output/file path/to/model_generation_station

# First set up paths
data_dir="/tmp/data/"
download_dir="${data_dir}UserAssessmentP/"
output_file="$1"
model_generation_station="$2"
assessments_data_util="${model_generation_station}/train_util/assessments"
download=true
if $download; then
    rm "${download_dir}/all_unfiltered.responses"
    for i in $(seq 7 -1 1)
    do
      # for each day in the last week download the user assessment data and save it
      d=`date --"date=$i day ago" +%Y-%m-%d`;
      mkdir -p "${download_dir}/dt=${d}";
      cd "${download_dir}/dt=${d}"
      s3cmd get --recursive s3://ka-mapreduce/entity_store/UserAssessmentP/dt=${d}/ --skip-existing
      zcat "${download_dir}dt=${d}"/* | python "${assessments_data_util}/get_user_assessment_data.py" >> "${download_dir}/all_unfiltered.responses"
    done;
    # Once all the data is gathered, make sure there are no duplicates, filter for assessments
    # where people were really trying, and output to the directory sent into the script
    cat "$download_dir"/all_unfiltered.responses | sort | uniq | "${assessments_data_util}/filter.py" >"${output_file}"
fi;

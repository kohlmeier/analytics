import re
import bson

import pymongo

import mongo_util
import mongo_examples

db_name = 'kadb'
mongo = pymongo.Connection() 
mongo_db = mongo[db_name]

def code(js):
    return bson.Code(js)

def monthly_video_exercise_activity(output_collection):

    map_vids_js = '''
    function () {
        var month = this.last_watched.getMonth()+1;
        var padded_month = month < 10 ? "0"+month : month;
        var date_key = (this.last_watched.getYear()+1900) + "-" + padded_month;
        var key = date_key + "|" + this.user;
        emit( key, {videos: 1, exercises: 0} );
    } 
    '''
    map_exs_js = '''
    function () {
        var month = this.first_done.getMonth()+1;
        var padded_month = month < 10 ? "0"+month : month;
        var date_key = (this.first_done.getYear()+1900) + "-" + padded_month;
        var key = date_key + "|" + this.user;
        emit( key, {videos: 0, exercises: 1} );
    }
    '''
    reduce_js = '''
    function(key, values) {
        var result = {videos: 0, exercises: 0};
    
        values.forEach(function(value) {
          result.videos += value.videos;
          result.exercises += value.exercises;
        });
        
        return result;
    }
    '''
    
    mongo_db['UserVideo'].map_reduce(code(map_vids_js), code(reduce_js), out="vid_ex_users") #, limit=1000000)
    print "UserVideo map complete"

    mongo_db['UserExercise'].map_reduce(code(map_exs_js), code(reduce_js), out={'reduce':'vid_ex_users'}) #, limit=1000000)
    print "UserExercise map complete"


    map_tab_js = 'function () { emit( this._id.split("|")[0], 1 ) }' 

    for (min_vid, min_ex) in [(0,0), (1,0), (5,0), (10,0), (25,0), (0,1), (0,5), (0,10), (0,25), (1,1), (5,5)]:
        desc = "min_vid=%d; min_ex=%d" % ( min_vid, min_ex )
        print desc
        query = {'value.exercises':{'$gte':min_ex}, 'value.videos':{'$gte':min_vid}}
        mongo_db['vid_ex_users'].map_reduce(code(map_tab_js), code(mongo_util.reduce_sum_js), out="temp_monthly", query=query)
        mongo_util.MongoUtil(db_name).copy_collection_into("temp_monthly", output_collection, add_flags={'tag':desc}, rename_id='month')

    

def monthly_badge_awards(output_collection):
    map = '''
    function () {
        var month = this.date.getMonth()+1;
        var date_key = (this.date.getYear()+1900) + "-" + (month < 10 ? "0"+month : month);
        var key = this.badge_name + "|" + date_key + "|" + this.user;
        emit( key, 1 );
    } 
    '''
    reduce = mongo_util.reduce_identity_js
    mongo_db['UserBadge'].map_reduce(code(map), code(reduce), out="temp_monthly")
    
    map = 'function () { emit( this._id.split("|")[0] + "|" + this._id.split("|")[1], 1 ) }'
    reduce = mongo_util.reduce_sum_js
    mongo_db['temp_monthly'].map_reduce(code(map), code(reduce), out="temp_monthly_2")
    
    for doc in mongo_db['temp_monthly_2'].find():
        newdoc = {'tag':'badge('+doc['_id'].split('|')[0]+')', 'month':doc['_id'].split('|')[1], 'value':doc['value']}
        mongo_db[output_collection].insert(newdoc)
    
    
    mongo_db.drop_collection('temp_monthly')
    mongo_db.drop_collection('temp_monthly_2')


def monthly_accounts(output_collection):
    map = '''
    function () {
        var month = this.joined.getMonth()+1;
        var date_key = (this.joined.getYear()+1900) + "-" + (month < 10 ? "0"+month : month);
        if (this.user_id.indexOf('nouserid') !== -1) {
            emit( date_key + "|phantom", 1)
        } else {
            emit(date_key + "|email", 1)
        }
    } 
    '''
    reduce = mongo_util.reduce_sum_js

    query = {'user_id':{'$exists':True}}
    mongo_db['UserData'].map_reduce(code(map), code(reduce), out="temp_registrations", query=query) #, limit=1000000)
    
    for doc in mongo_db['temp_registrations'].find():
        newdoc = {'tag':'registration('+doc['_id'].split('|')[1]+')', 'month':doc['_id'].split('|')[0], 'value':doc['value']}
        mongo_db[output_collection].insert(newdoc)
    
    mongo_db.drop_collection('temp_registrations')


def cohort_analysis(min_group=0, no_coach=False):
    # min_group is the minimum size of the group coached by the users coach
    # if no_coach==True then only users with no coach are included
    
    # TODO(jace) would be more correct to base this off of 
    # ProblemLog/VideoLog (vs UserExercise/UserVideo)
    
    # TODO(jace): since I'm re-using this, it shouldn't live in _examples, 
    # but I'm punting until we know what the future of mongo at KA is 
    mongo_examples.generate_cohort_maps()
    
    # load the map of cohort users, so we can cross-section by that if we want
    if min_group > 0 or no_coach:
        group_sizes = mongo_util.MongoUtil(db_name).load_collection_as_map('user_max_cohort_size', 'user')
    
    # keyed by month, values are a map of month to {'visits': visits, 'users': users}
    cohorts = {}
    
    # walk through registered (non-phantom) users
    count = 0
    query = {'user_id':{'$exists':True, '$not':re.compile('/.*nouserid.*/')}}
    for user_data in mongo_db['UserData'].find(query):
        user = user_data['user']
        
        if min_group > 0 and (
                user not in group_sizes or 
                group_sizes[user]['max_cohort_size'] < min_group):
            continue
        if no_coach and user in group_sizes:
            continue
              
        cohort_month = user_data['joined'].strftime('%Y-%m')
        if cohort_month not in cohorts:
            cohorts[cohort_month] = {}

        # for each registered user, create a list days they have visited
        visits = [ user_data['joined'].strftime('%Y-%m-%d') ]

        def include_visit_date(dt):
            if dt is None:
                return
            
            date_string = dt.strftime('%Y-%m-%d')
            if date_string not in visits:
                visits.append(date_string)
        
        for user_video in mongo_db['UserVideo'].find( {'user': user} ):
            include_visit_date(user_video['last_watched'])
        
        for user_exercise in mongo_db['UserExercise'].find( {'user': user} ):
            include_visit_date(user_exercise['first_done'])
            include_visit_date(user_exercise['last_done'])
            include_visit_date(user_exercise['proficient_date'])
        
        # roll this user's list of visit dates up into the monthly cohort stats
        cohort = cohorts[cohort_month]
        visit_months = []

        for visit in visits:
            month = visit[:7]
                
            if month not in cohort:
                cohort[month] = {'users':0, 'visits':0}
            
            cohort[month]['visits'] += 1
            
            if month not in visit_months:
                visit_months.append(month)
                cohort[month]['users'] += 1
                
        count += 1
        if count % 10000 == 0:
            print "Processed %d users." % count
                
    out_collection = 'report_cohort_analysis_%d%s' % (min_group, '_nocoach' if no_coach else '')
    mongo_db.drop_collection(out_collection)
    
    for cohort_name, cohort in cohorts.iteritems():
        for month, month_stats in cohort.iteritems():
            doc = {'cohort':cohort_name, 'month':month, 'users':month_stats['users'], 'visits':month_stats['visits']}
            mongo_db[out_collection].insert(doc)
    

def main():
    
    output_collection = 'report_monthly_counts' 
    
    # start clean if output collection exists
    mongo_db.drop_collection(output_collection) 

    monthly_video_exercise_activity(output_collection)
    monthly_accounts(output_collection)
        
    cohort_analysis()
    cohort_analysis(min_group=1)
    cohort_analysis(min_group=10)
    cohort_analysis(no_coach=True)

if __name__ == '__main__':
    main()



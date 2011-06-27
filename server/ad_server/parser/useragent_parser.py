def get_os(user_agent_string):
    """ Returns 'iOS', 'android' or 'other' """
    """ Returns the appropriate float for the os version """
    user_os_name = None
    try:    
        if "like Mac OS X" in user_agent_string:
            user_os_name = 'iOS'
        elif "Android" in user_agent_string:
            user_os_name = 'android'

        if user_os_name == 'android':
            num_start = user_agent_string.find('Android')+8
            num_end = user_agent_string.find(';', num_start)
        elif user_os_name == 'iOS':
            if user_agent_string.find('iPhone OS') != -1:
                num_start = user_agent_string.find('iPhone OS')+10
            else:
                num_start = user_agent_string.find('CPU OS')+7
            num_end = user_agent_string.find(' ', num_start)
    
        if '_' in user_agent_string[num_start:num_end]:
            user_agent_string = user_agent_string.replace('_','.')
    
        for n in user_agent_string[num_start:num_end].split('.'):
            int(n)
            
        user_os_version = user_agent_string[num_start:num_end]
    except:
        user_os_version = None
    
    return user_os_name, user_os_version
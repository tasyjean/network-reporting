﻿$(function() {
   $("#loginCredentials").submit(function(event) {
	   event.preventDefault();
	   // Check if data submited is valid.
	   $.ajax({url: 'http://checklogincredentials.mopub.com:8888',
		   data: $(this).serialize(),
		   crossDomain: true, 
		   dataType: "jsonp",
	           success: function(valid) {
	           	   // Upon success update the database
			   if (valid) {
				if (account_key) {
                  window.location = "/ad_network_reports/manage/" + account_key;
				} else {
                  window.location = "/ad_network_reports/";
				}
			   } else {
				$("#error").html("Invalid login information.")
			   }
		   }
	   });
    });
})

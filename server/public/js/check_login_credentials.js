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
			   	$.post("/ad_network_reports/add/",
		           		$("#loginCredentials").serialize());
				window.location = "/ad_network_reports/";
			   } else {
			   	$("#error").html("Invalid login information.")
			   }
		   }
	   });
    });
})
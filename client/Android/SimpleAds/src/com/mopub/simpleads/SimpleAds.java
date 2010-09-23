package com.mopub.simpleads;

import com.mopub.mobileads.AdView;

import android.app.Activity;
import android.content.Context;
import android.os.Bundle;
import android.view.View;
import android.view.View.OnClickListener;
import android.view.inputmethod.InputMethodManager;
import android.widget.Button;
import android.widget.EditText;

public class SimpleAds extends Activity {
	private AdView				mTopAdView = null;
	private AdView				mMidAdView = null;
	
	private Button				mSearchButton = null;
	private EditText			mSearchText = null;

    /** Called when the activity is first created. */
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.main);
        
		// Initialize Ad components
        mTopAdView = (AdView) findViewById(R.id.topadview);
        mTopAdView.setAdUnitId("agltb3B1Yi1pbmNyDAsSBFNpdGUYudkDDA");
        mTopAdView.loadAd();
		
        mMidAdView = (AdView) findViewById(R.id.middleadview);
        mMidAdView.setAdUnitId("agltb3B1Yi1pbmNyDAsSBFNpdGUYoeEDDA");
        mMidAdView.loadAd();
		
        mSearchText = (EditText) findViewById(R.id.searchtext);
        mSearchButton = (Button) findViewById(R.id.searchbutton);
        mSearchButton.setOnClickListener(new OnClickListener() {
			public void onClick(View v) {
				InputMethodManager imm = (InputMethodManager)getSystemService(Context.INPUT_METHOD_SERVICE);
				imm.hideSoftInputFromWindow(mSearchText.getWindowToken(), 0);
				mTopAdView.setKeywords(mSearchText.getText().toString());
				mMidAdView.setKeywords(mSearchText.getText().toString());
				mTopAdView.loadAd();
				mMidAdView.loadAd();
			}
		});
    }
}
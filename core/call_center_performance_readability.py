"""Readability polish for call-center performance metrics.

This is deliberately CSS-only and role-scoped through the existing call-center
response injection. It preserves the dashboard structure while using spare
horizontal space inside performance cards for the explanatory copy.
"""

_PERFORMANCE_READABILITY_STYLE = r'''<style id="greenlife-call-center-performance-readability-v1">
@media (min-width:1100px){
  /* Keep the existing performance layout, but make secondary copy genuinely readable. */
  body.gl-role-call-center .cc-v5 .cc-v7-performance-head p{
    color:#56677c!important;
    font-size:10.5px!important;
    font-weight:700!important;
    line-height:1.75!important;
    opacity:1!important
  }

  body.gl-role-call-center .cc-v5 .cc-v7-metric{
    min-height:88px!important;
    padding:11px 13px!important;
    display:grid!important;
    grid-template-columns:max-content minmax(0,1fr)!important;
    grid-template-rows:auto 1fr!important;
    column-gap:14px!important;
    row-gap:7px!important;
    align-items:center!important
  }
  body.gl-role-call-center .cc-v5 .cc-v7-metric>span{
    grid-column:1 / -1!important;
    margin:0!important;
    color:#34485f!important;
    font-size:11px!important;
    font-weight:900!important;
    line-height:1.45!important;
    opacity:1!important
  }
  body.gl-role-call-center .cc-v5 .cc-v7-metric>strong{
    grid-column:1!important;
    grid-row:2!important;
    margin:0!important;
    color:#1f3047!important;
    font-size:27px!important;
    font-weight:900!important;
    line-height:1!important;
    white-space:nowrap!important
  }
  body.gl-role-call-center .cc-v5 .cc-v7-metric>small{
    grid-column:2!important;
    grid-row:2!important;
    margin:0!important;
    color:#4c5f75!important;
    font-size:10.5px!important;
    font-weight:750!important;
    line-height:1.7!important;
    opacity:1!important;
    align-self:center!important
  }
  body.gl-role-call-center .cc-v5 .cc-v7-metric.attention>strong{color:#973b53!important}
  body.gl-role-call-center .cc-v5 .cc-v7-metric.good>strong{color:#236b4d!important}
  body.gl-role-call-center .cc-v5 .cc-v7-metric.purple>strong{color:#5b3f82!important}

  /* The funnel is part of the same block; remove the washed-out grey there too. */
  body.gl-role-call-center .cc-v5 .cc-v7-funnel-step span{
    color:#405269!important;
    font-size:10px!important;
    font-weight:850!important;
    line-height:1.45!important;
    opacity:1!important
  }
  body.gl-role-call-center .cc-v5 .cc-v7-funnel-step b{
    color:#1d2e44!important;
    font-size:18px!important;
    font-weight:900!important
  }
}

/* On narrower desktop widths, keep the familiar vertical stack to prevent crowding. */
@media (min-width:1100px) and (max-width:1280px){
  body.gl-role-call-center .cc-v5 .cc-v7-metric{
    display:block!important;
    min-height:88px!important
  }
  body.gl-role-call-center .cc-v5 .cc-v7-metric>span{display:block!important}
  body.gl-role-call-center .cc-v5 .cc-v7-metric>strong{display:block!important;margin-top:6px!important;font-size:25px!important}
  body.gl-role-call-center .cc-v5 .cc-v7-metric>small{display:block!important;margin-top:6px!important;font-size:10px!important;line-height:1.6!important}
}
</style>'''


def install_call_center_performance_readability():
    """Append the performance readability CSS to call-center staff responses."""
    from . import call_center_views

    if 'greenlife-call-center-performance-readability-v1' in call_center_views._CALL_CENTER_STAFF_STYLE:
        return
    call_center_views._CALL_CENTER_STAFF_STYLE += _PERFORMANCE_READABILITY_STYLE

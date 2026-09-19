"""Fine-tune call-center lead action widths so long call-status labels never clip."""

_ACTION_LAYOUT_STYLE = r'''<style id="greenlife-call-center-action-layout-v1">
@media (min-width:1100px){
  /* Use the spare monitor width for the action area and reserve more room for
     the long call-status control (تماس انجام شد / تماس گرفته شد). */
  body.gl-role-call-center .cc-v5 .cc-v5-patient{
    grid-template-columns:minmax(270px,1.25fr) minmax(145px,.78fr) 112px 116px minmax(372px,420px)!important;
  }
  body.gl-role-call-center .cc-v5 .cc-v5-row-actions{
    min-width:372px!important;
    width:100%!important;
    display:grid!important;
    grid-template-columns:minmax(64px,.82fr) minmax(82px,1.05fr) minmax(68px,.9fr) minmax(116px,1.42fr)!important;
    gap:6px!important;
    align-items:center!important;
    justify-content:stretch!important;
    justify-self:end!important;
  }
  body.gl-role-call-center .cc-v5 .cc-v5-row-actions>a,
  body.gl-role-call-center .cc-v5 .cc-v5-row-actions>button{
    width:100%!important;
    min-width:0!important;
    max-width:none!important;
    overflow:visible!important;
    text-overflow:clip!important;
    padding-inline:7px!important;
    white-space:nowrap!important;
  }
  body.gl-role-call-center .cc-v5 .cc-contact-done{
    min-width:116px!important;
    font-size:9.6px!important;
    letter-spacing:-.05px!important;
    padding-inline:9px!important;
  }
  body.gl-role-call-center .cc-v5 a.cc-v5-action[href*="status=contacted"]{
    min-width:118px!important;
    padding-inline:10px!important;
    white-space:nowrap!important;
  }
}

@media (min-width:1100px) and (max-width:1400px){
  body.gl-role-call-center .cc-v5 .cc-v5-patient{
    grid-template-columns:minmax(225px,1.08fr) minmax(112px,.66fr) 100px 104px minmax(326px,350px)!important;
    gap:8px!important;
  }
  body.gl-role-call-center .cc-v5 .cc-v5-row-actions{
    min-width:326px!important;
    grid-template-columns:minmax(54px,.76fr) minmax(69px,1fr) minmax(57px,.84fr) minmax(103px,1.48fr)!important;
    gap:5px!important;
  }
  body.gl-role-call-center .cc-v5 .cc-v5-row-actions>a,
  body.gl-role-call-center .cc-v5 .cc-v5-row-actions>button{
    font-size:8.9px!important;
    padding-inline:4px!important;
  }
  body.gl-role-call-center .cc-v5 .cc-contact-done{
    min-width:103px!important;
    font-size:8.8px!important;
    padding-inline:5px!important;
  }
}

/* v2 final visual override — loaded last, so this is what operators actually see. */
@media (min-width:1100px){
 body.gl-role-call-center .cc-v5 .cc-v5-row-actions{gap:8px!important}
 body.gl-role-call-center .cc-v5 .cc-v5-row-actions>a,
 body.gl-role-call-center .cc-v5 .cc-v5-row-actions>button{
   height:40px!important;min-height:40px!important;border-radius:12px!important;
   font:900 10px Tahoma!important;box-shadow:0 3px 10px rgba(35,49,70,.055)!important
 }
 body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-v5-call{
   background:#edf8f3!important;color:#17684b!important;border:1px solid #c6e2d5!important
 }
 body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-v5-open,
 body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-result-action{
   background:#f5f1fa!important;color:#604786!important;border:1px solid #ddd3e9!important
 }
 body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-whatsapp-action{
   background:#f0f8f4!important;color:#287052!important;border:1px solid #cfe4d8!important
 }
 body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-contact-done{
   background:#e8f1ef!important;color:#285f55!important;border:1px solid #bfd5d0!important;
   min-width:116px!important
 }
 body.gl-role-call-center .cc-v5 .cc-v5-row-actions .cc-contact-done[disabled]{
   background:#f3f5f6!important;color:#77828c!important;border-color:#e0e5e8!important
 }
}
</style>'''


def install_call_center_action_layout():
    """Append the lead action-width override to staff call-center responses."""
    from . import call_center_views

    if 'greenlife-call-center-action-layout-v1' not in call_center_views._CALL_CENTER_STAFF_STYLE:
        call_center_views._CALL_CENTER_STAFF_STYLE += _ACTION_LAYOUT_STYLE

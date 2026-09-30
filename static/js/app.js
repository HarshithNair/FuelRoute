'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const number = (n, digits=0) => new Intl.NumberFormat('en-US', {maximumFractionDigits:digits}).format(n);
  const dollars = n => new Intl.NumberFormat('en-US',{style:'currency',currency:'USD'}).format(n);
  const escapeHTML = text => String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let map, layer, bounds, currentPlan, markers=[];
  if (window.L) {
    map = L.map('map',{zoomControl:false,scrollWheelZoom:false}).setView([38.7,-97.5],4);
    L.control.zoom({position:'topright'}).addTo(map);
    // A local public-domain regional basemap avoids tile-server/API-key
    // dependencies. Routing and station coordinates still come from real OSM.
    map.createPane('basemap'); map.getPane('basemap').style.zIndex=200;
    map.createPane('maplabels'); map.getPane('maplabels').style.zIndex=250;
    map.getPane('maplabels').style.pointerEvents='none';
    map.attributionControl.addAttribution('Map: <a href="https://www.naturalearthdata.com/">Natural Earth</a> · Route/POIs: <a href="https://www.openstreetmap.org/copyright">OSM</a>');
    Promise.all(['countries','states','cities'].map(key=>fetch($('map').dataset[key]).then(r=>{if(!r.ok)throw new Error('Basemap unavailable');return r.json();}))).then(([countries,states,cities])=>{
      L.geoJSON(countries,{pane:'basemap',interactive:false,style:{fillColor:'#edf0e9',fillOpacity:1,color:'#cdd7cd',weight:1}}).addTo(map);
      L.geoJSON(states,{pane:'basemap',interactive:false,style:{fillColor:'#f3f5ef',fillOpacity:1,color:'#d5ddd2',weight:1}}).addTo(map);
      const labels=L.layerGroup();
      states.features.forEach(feature=>{
        const p=feature.properties;
        if(p.latitude && p.longitude) L.marker([p.latitude,p.longitude],{pane:'maplabels',interactive:false,icon:L.divIcon({className:'state-label',html:escapeHTML(p.name),iconSize:[100,14],iconAnchor:[50,7]})}).addTo(labels);
      });
      labels.addTo(map);
      L.geoJSON(cities,{pane:'maplabels',pointToLayer:(feature,ll)=>L.circleMarker(ll,{pane:'maplabels',radius:2,fillColor:'#839586',color:'#839586',weight:0,fillOpacity:.7,interactive:false}).bindTooltip(escapeHTML(feature.properties.NAME),{permanent:true,direction:'right',className:'city-label',pane:'maplabels',opacity:1})}).addTo(map);
      map.on('zoomend',()=>{if(map.getZoom()>6)map.removeLayer(labels);else if(!map.hasLayer(labels))labels.addTo(map);});
    }).catch(()=>{$('map-empty').querySelector('strong').textContent='Basemap unavailable. Route plotting still works.';});
    layer=L.featureGroup().addTo(map);
  } else {
    $('map-empty').querySelector('strong').textContent='The map could not load.';
    $('map-empty').querySelector('p').textContent='Route calculations are still available. Reload to retry the map.';
  }
  const pin = (label, kind='') => L.divIcon({className:`map-pin ${kind}`,html:String(label),iconSize:[30,30],iconAnchor:[15,15]});
  function render(plan) {
    currentPlan=plan;
    $('data-status').textContent=`${number(plan.data_coverage.stations)} fuel stations · ${number(plan.data_coverage.located)} mapped`;
    $('distance').innerHTML=`${number(plan.total_distance_miles)} <small>mi</small>`;
    $('gallons').innerHTML=`${number(plan.total_gallons,1)} <small>gal</small>`;
    $('duration').textContent=`${number(plan.duration_hours,1)} hr driving · excludes stops`;
    $('stops-count').textContent=plan.fuel_stops.length;
    $('stop-badge').textContent=plan.fuel_stops.length;
    $('total-cost').textContent=dollars(plan.total_fuel_cost);
    $('stops-subtitle').textContent=`${number(plan.candidate_stations)} nearby stations compared · 500-mile maximum leg`;
    $('stops-body').replaceChildren();
    markers=[];
    if(map) {
      layer.clearLayers();
      L.polyline(plan.route_geometry.map(([lon,lat])=>[lat,lon]),{color:'#18815d',weight:4,opacity:.9}).addTo(layer);
      for(const [key,label,kind] of [['start','A','start'],['finish','B','finish']]) {
        const loc=plan[key];
        L.marker([loc.latitude,loc.longitude],{icon:pin(label,kind)}).bindPopup(`<strong>${key==='start'?'Start':'Destination'}</strong><br>${escapeHTML(loc.name)}`).addTo(layer);
      }
    }
    plan.fuel_stops.forEach((stop,i) => {
      if(map) {
        const marker=L.marker([stop.latitude,stop.longitude],{icon:pin(i+1)}).bindPopup(`<strong>${i+1}. ${escapeHTML(stop.name)}</strong><br>${escapeHTML(stop.city)}, ${escapeHTML(stop.state)}<br>${number(stop.distance_into_route,1)} mi into route<br>$${Number(stop.price_per_gallon).toFixed(3)}/gal · ${number(stop.gallons,2)} gal<br>Purchase: <strong>${dollars(stop.cost)}</strong><br>Estimated round-trip access: ${number(stop.detour_miles,1)} mi`).addTo(layer);
        markers.push(marker);
        if(stop.route_point && stop.detour_miles>.02) L.polyline([[stop.latitude,stop.longitude],[stop.route_point[1],stop.route_point[0]]],{color:'#7c9e88',weight:2,dashArray:'4 5'}).bindTooltip('Estimated station access; not driving directions').addTo(layer);
      }
      const row=document.createElement('tr');
      row.innerHTML=`<td><div class="station-cell"><span class="stop-number">${i+1}</span><div><strong class="station-title">${escapeHTML(stop.name)}</strong><span class="station-city">${escapeHTML(stop.city)}, ${escapeHTML(stop.state)}</span></div></div></td><td>${number(stop.distance_into_route)} mi</td><td>$${Number(stop.price_per_gallon).toFixed(3)}</td><td>${number(stop.gallons,2)} gal</td><td>${dollars(stop.cost)}</td><td><button type="button" aria-label="Show stop ${i+1} on map" title="Show on map">↗</button></td>`;
      row.querySelector('button').addEventListener('click',()=>{if(!map)return;map.setView([stop.latitude,stop.longitude],9);markers[i].openPopup();$('map').scrollIntoView({behavior:'smooth',block:'center'});});
      row.querySelector('button').disabled=!map;
      $('stops-body').append(row);
    });
    if(map) {bounds=layer.getBounds();map.fitBounds(bounds,{padding:[32,32]});$('map-empty').hidden=true;}
    $('stops-table-wrap').hidden=!plan.fuel_stops.length;
    $('stops-empty').hidden=!!plan.fuel_stops.length;
    if(!plan.fuel_stops.length) {
      $('stops-empty').querySelector('strong').textContent='You’re ready to go. No fuel stops needed.';
      $('stops-empty').querySelector('p').textContent='Your full starting tank covers this journey.';
    }
    $('cost-breakdown').hidden=false;
    $('cost-breakdown').innerHTML=`<span>Starting fuel consumed <strong>${dollars(plan.initial_fuel_cost)}</strong></span><span>Fuel purchases <strong>${dollars(plan.fuel_purchase_cost)}</strong></span><span>Estimated detours <strong>${number(plan.detour_miles,1)} mi</strong></span>`;
    $('assumptions').textContent=`Starting fuel valued at $${Number(plan.initial_fuel_price).toFixed(3)}/gal (${plan.initial_price_source}). ${plan.data_coverage.located.toLocaleString()} of ${plan.data_coverage.stations.toLocaleString()} stations have coordinates. Prices are a dataset snapshot. Detours are geometric estimates, not verified road directions; confirm station access. Driving time excludes detours and refueling.`;
    $('download').hidden=false;
  }
  function resetResults() {
    currentPlan=null;markers=[];bounds=null;
    if(layer) layer.clearLayers();
    for(const id of ['distance','gallons','stops-count','total-cost']) $(id).textContent='—';
    $('duration').textContent='Your full journey';$('stop-badge').textContent='0';
    $('stops-subtitle').textContent='The right fuel, at the right place.';
    $('assumptions').textContent='Prices are from the supplied assessment dataset. Station access distances are estimates; confirm road access before traveling.';
    $('stops-body').replaceChildren();$('stops-table-wrap').hidden=true;
    $('cost-breakdown').hidden=true;$('download').hidden=true;$('stops-empty').hidden=false;
    $('stops-empty').querySelector('strong').textContent='Your next adventure starts with a plan.';
    $('stops-empty').querySelector('p').textContent='Calculate a route to see your recommended fuel stops here.';
    $('map-empty').hidden=false;
  }
  $('route-form').addEventListener('submit',async event=>{
    event.preventDefault();$('error').hidden=true;resetResults();
    const payload={start:$('start').value.trim(),finish:$('finish').value.trim()};
    if($('initial-price').value)payload.initial_fuel_price=$('initial-price').value;
    $('loading').hidden=false;$('summary').classList.add('busy');$('calculate').disabled=true;$('swap').disabled=true;
    $('button-label').textContent='Finding your route…';$('route-form').setAttribute('aria-busy','true');
    const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),110000);
    try {
      const response=await fetch('/api/route/',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload),signal:controller.signal});
      const data=await response.json();
      if(!response.ok) {
        const error=data.error||{};
        const details=error.details;
        const extra=details && !details.detail ? Object.values(details).flat().join(' ') : '';
        throw new Error(`${error.message||'Unable to calculate this route.'} ${extra}`.trim());
      }
      render(data);
    } catch(error) {
      $('error').textContent=error.name==='AbortError'?'The route request timed out. Please try again.':error.message;
      $('error').hidden=false;
    } finally {
      clearTimeout(timer);$('loading').hidden=true;$('summary').classList.remove('busy');$('calculate').disabled=false;$('swap').disabled=false;$('button-label').textContent='Find Optimal Route';$('route-form').setAttribute('aria-busy','false');
    }
  });
  $('swap').addEventListener('click',()=>{const a=$('start').value;$('start').value=$('finish').value;$('finish').value=a;});
  $('fit-map').addEventListener('click',()=>{if(!map)return;bounds?map.fitBounds(bounds,{padding:[32,32]}):map.setView([38.7,-97.5],4);});
  $('download').addEventListener('click',()=>{if(!currentPlan)return;const url=URL.createObjectURL(new Blob([JSON.stringify(currentPlan,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='fuelroute-plan.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
  fetch('/api/status/').then(r=>{if(!r.ok)throw new Error();return r.json();}).then(data=>{$('data-status').textContent=data.ready?`${number(data.stations)} fuel stations · ${number(data.located)} mapped`:'Fuel dataset not loaded yet';}).catch(()=>{$('data-status').textContent='Fuel data status unavailable';});
})();

function [display, state] = update_multisource_tracks(detections, state, dt)
% Track up to three acoustic directions/positions across analysis windows.
% Explicit state makes this independent of MATLAB persistent variables.
% Coordinates are emitted only for measurements that passed the range guard.
if nargin < 2 || isempty(state)
    state = struct('tracks', emptyTracks(), 'nextId', 1);
end
if nargin < 3 || isempty(dt), dt = .25; end
assert(isscalar(dt) && isfinite(dt) && dt > 0 && dt <= 5);
% A corrupt subnormal interval can overflow direction/velocity divisions.
if dt < .001, dt = .25; end
if isstruct(detections) && isfield(detections, 'sources')
    detections = detections.sources;
end
if isempty(detections), detections = struct([]); end
assert(numel(detections) <= 3, 'At most three detections are supported.');
tracks = state.tracks;
used = false(1, numel(detections));
matched = false(1, numel(tracks));
% Predicting from velocity retains identity when two moving paths approach.
if ~isempty(tracks) && ~isfield(tracks,'observedDirection')
    for j = 1:numel(tracks)
        tracks(j).observedDirection = tracks(j).direction;
        tracks(j).directionVelocity = [0 0 0];
        tracks(j).predictedDirection = tracks(j).direction;
    end
end
for j = 1:numel(tracks)
    tracks(j).predicted = tracks(j).position + tracks(j).velocity * dt;
    tracks(j).predictedDirection = unit(tracks(j).observedDirection + ...
        tracks(j).directionVelocity * dt);
end
% Global one-to-one association: at most 4^3=64 bounded assignments.
% A greedy match can consume the only valid observation of a second track.
costs=inf(3,3);
for i=1:numel(tracks)
    for j=1:numel(detections)
        d=detections(j);
        angle=acosd(max(-1,min(1,dot(tracks(i).predictedDirection,unit(d.direction)))));
        if angle>32,continue;end
        cost=angle/22;
        if ~validPosition(d),cost=cost+.5;end
        if validPosition(d) && all(isfinite(tracks(i).position))
            separation=norm(tracks(i).predicted-d.position);
            gate=max(.18,.55*dt+.08*tracks(i).misses);
            hardGate=max(gate,2.0*dt);
            if separation>hardGate,continue;end
            cost=cost+separation/gate;
        end
        costs(i,j)=cost;
    end
end
assignment=[4 4 4];bestMatches=-1;bestCost=inf;
for code=0:63
    choices=[bitand(code,3),bitand(bitshift(code,-2),3),bitand(bitshift(code,-4),3)]+1;
    chosen=choices(choices<4);
    if numel(unique(chosen))~=numel(chosen),continue;end
    total=0;legal=true;
    for i=1:3
        if choices(i)<4
            if ~isfinite(costs(i,choices(i))),legal=false;break;end
            total=total+costs(i,choices(i));
        end
    end
    matches=numel(chosen);
    if legal && (matches>bestMatches || (matches==bestMatches && total<bestCost))
        assignment=choices;bestMatches=matches;bestCost=total;
    end
end
for i=1:numel(tracks)
    j=assignment(i);
    if j<4
        tracks(i)=advanceTrack(tracks(i),detections(j),dt);
        matched(i)=true;used(j)=true;
    end
end
for i = 1:numel(tracks)
    if ~matched(i)
        if tracks(i).hits<2,tracks(i).hits=0;end
        tracks(i).misses = tracks(i).misses + 1;
        tracks(i).velocity = .5 * tracks(i).velocity;
        tracks(i).directionVelocity = .5 * tracks(i).directionVelocity;
    end
end
tracks = tracks([tracks.misses] <= 3);
for j = find(~used)
    if numel(tracks) >= 3, break; end
    d = detections(j); t = trackTemplate();
    t.id = state.nextId; state.nextId = state.nextId + 1;
    t.direction = unit(d.direction);
    t.observedDirection = t.direction;
    t.rangeReliable = validPosition(d);
    if t.rangeReliable, t.position = d.position; end
    t.hits = 1; tracks(end+1) = t;
end
state.tracks = tracks;
display = repmat(struct('id',0,'position',[NaN NaN NaN],...
    'direction',[NaN NaN NaN],'rangeReliable',false,'held',false,...
    'confirmed',false,'ageFrames',0,'missedFrames',0),1,numel(tracks));
for i = 1:numel(tracks)
    t = tracks(i); display(i).id = t.id;
    if t.rangeReliable, display(i).position = t.position; end
    display(i).direction = t.direction;
    display(i).rangeReliable = t.rangeReliable;
    display(i).held = t.misses > 0;
    display(i).confirmed = t.hits >= 2;
    display(i).ageFrames = t.age;
    display(i).missedFrames = t.misses;
end
end

function t = advanceTrack(t,d,dt)
direction = unit(d.direction);
rate = (direction - t.observedDirection) / dt;
rateNorm = norm(rate);
if rateNorm > 1, rate = rate / rateNorm; end
t.directionVelocity = .65 * rate + .35 * t.directionVelocity;
t.observedDirection = direction;
t.direction = unit(.65 * direction + .35 * t.direction);
if validPosition(d)
    if ~t.rangeReliable
        % Preserve the existing static deadband across a temporary loss of
        % range. Never emit old XYZ while the current range is invalid.
        if ~all(isfinite(t.position)) || norm(d.position-t.position)>.05
            t.position = d.position; t.velocity = [0 0 0];
        else
            t.velocity = .35*t.velocity;
        end
    else
        residual = d.position - t.position;
        % A stationary source should not visibly wander on each frame.
        if norm(residual) > .05
            predicted = t.position + t.velocity * dt;
            correction = d.position - predicted;
            t.position = predicted + .72 * correction;
            t.velocity = .55 * t.velocity + .28 * correction / dt;
            speed = norm(t.velocity);
            if speed > 1.2, t.velocity = t.velocity * (1.2 / speed); end
        else
            t.velocity = .35 * t.velocity;
        end
    end
    t.rangeReliable = true;
else
    % A new direction-only observation must not inherit an old XYZ label.
    if all(isfinite(t.position))
        t.position=t.position+t.velocity*dt;t.velocity=.8*t.velocity;
        if norm(t.velocity)>.1
            t.position=norm(t.position)*direction;
        end
    end
    t.rangeReliable = false;
end
t.hits = min(2,t.hits + 1); t.age = min(2147483647,t.age + 1); t.misses = 0;
end

function ok = validPosition(d)
ok = isfield(d,'rangeReliable') && logical(d.rangeReliable) && ...
    isfield(d,'position') && numel(d.position)==3 && all(isfinite(d.position));
end

function u = unit(x)
x = reshape(x,1,3); u = x / max(norm(x),eps);
end

function t = trackTemplate()
t = struct('id',0,'position',[NaN NaN NaN],'direction',[1 0 0],...
    'observedDirection',[1 0 0],'predictedDirection',[1 0 0],...
    'directionVelocity',[0 0 0],...
    'velocity',[0 0 0],'predicted',[NaN NaN NaN],...
    'rangeReliable',false,'hits',0,'age',1,'misses',0);
end

function tracks = emptyTracks()
tracks = repmat(trackTemplate(),1,0);
end



